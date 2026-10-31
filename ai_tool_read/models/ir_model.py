# Copyright 2026 Quartile (https://www.quartile.co)
# Copyright 2026 Stefano Savanelli
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from datetime import date

from odoo import models
from odoo.exceptions import UserError

from odoo.addons.ai_tool.tools import aitool

MAX_LIMIT = 200
DEFAULT_GROUP_LIMIT = 100
MAX_GROUP_LIMIT = 500
# PostgreSQL aggregates that return a value of the field's own kind. The ORM
# also accepts "recordset" and "array_agg", which return the records or values
# themselves: left out, search_read is the tool to read records.
AGGREGATE_FUNCTIONS = (
    "count",
    "count_distinct",
    "sum",
    "avg",
    "min",
    "max",
    "bool_and",
    "bool_or",
)


class IrModel(models.Model):
    _inherit = "ir.model"

    def _ai_forbidden_fields(self):
        """Return the fields forbidden to AI.

        A flag set on a mixin's field applies to the models inheriting it. Every
        field that depends on a flagged one is forbidden too, as it exposes its
        value: related fields, ``_inherits`` included, and computed fields,
        transitively (``res.partner.email`` takes ``email_formatted`` and
        ``res.users.email`` along). The flags are metadata regular users cannot
        read, hence the sudo.
        """
        registry = self.env.registry
        forbidden = set()
        flags = self.env["ir.model.fields"].sudo().search([("ai_no_read", "=", True)])
        if not flags:
            return forbidden
        # Skip a flag left on a model or field that is gone from the code.
        for flag in flags.filtered(
            lambda rec: rec.model in registry
            and rec.name in registry[rec.model]._fields
        ):
            flagged_class = registry[flag.model]
            forbidden.update(
                model_class._fields[flag.name]
                for model_class in registry.models.values()
                if issubclass(model_class, flagged_class)
            )
        for field in list(forbidden):
            forbidden.update(registry.get_dependent_fields(field))
        return forbidden

    def _ai_readable_field_names(self, model):
        """Return the field names of ``model`` the tools may return.

        A field is left out when it is forbidden to AI, binary, restricted by
        ``groups=`` for the caller (as ``fields_get`` does), or relational to a
        model the caller cannot read, which would fail the whole read. So is a
        ``display_name`` computed on the fly: ``name_get`` may show another
        record's name (``mail.followers``) with nothing in its dependencies to
        tell. A stored one declares its dependencies, like any computed field.
        """
        target = self.env[model]
        forbidden = self._ai_forbidden_fields()
        return {
            name
            for name, field in target._fields.items()
            if field not in forbidden
            and field.type != "binary"
            and (field.store or name != "display_name")
            and (
                not field.groups
                or self.env.su
                or self.env.user.has_groups(field.groups)
            )
            and (
                not field.relational or self.env[field.comodel_name].has_access("read")
            )
        }

    def _ai_is_queryable_model(self, model):
        """Whether ``model`` is a concrete model. ``ir.model`` also lists
        abstract models, some with a read ACL (``board.board``), and wizards:
        neither can be searched."""
        return model in self.env and not (
            self.env[model]._abstract or self.env[model]._transient
        )

    def _ai_target(self, model):
        """Resolve ``model`` to a recordset, checking that it can be searched
        and that the caller has read access (data is never read as sudo)."""
        if not self._ai_is_queryable_model(model):
            raise UserError(
                self.env._(
                    "Model '%(model)s' does not exist or cannot be read.", model=model
                )
            )
        target = self.env[model]
        target.check_access("read")
        return target

    def _ai_can_read(self, records, field_names):
        """Whether ``field_names`` can be read on ``records`` by the caller."""
        try:
            records.read(field_names, load=None)
        except UserError:
            return False
        return True

    def _ai_read(self, records, field_names):
        """Read ``field_names`` on ``records``; return the rows and the names of
        the fields left out.

        Searching and reading do not always agree: a record can be found and
        then refused (``ir.attachment``), and a computed field can fail from its
        compute (``signup_url`` of a partner with a user). When the plain read
        fails, refused records are dropped without notice, as record rules would
        drop them, and refused fields are probed one by one and left out.
        ``AccessError`` is a ``UserError``; anything else still propagates.
        """
        try:
            return records.read(field_names, load=None), []
        except UserError:
            records = records.filtered(lambda rec: self._ai_can_read(rec, ["id"]))
        refused = [
            name for name in field_names if not self._ai_can_read(records, [name])
        ]
        kept = [name for name in field_names if name not in refused]
        # Never read an empty list: Odoo reads *all* fields for it.
        return records.read(kept or ["id"], load=None), refused

    def _ai_jsonify(self, row):
        """Make a ``search_read`` row JSON-serializable (dates to ISO strings).

        ``isinstance(value, date)`` also covers ``datetime``, a subclass."""

        return {
            key: value.isoformat() if isinstance(value, date) else value
            for key, value in row.items()
        }

    @aitool(
        input_schema={},
        output_schema={
            "models": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "name": {"type": "string"},
                    },
                },
            },
        },
    )
    def _ai_list_models(self):
        """List the concrete models the caller is allowed to read, leaving out
        those gone from the registry."""
        result = []
        # Listing every readable model is the point of the tool.
        for record in self.sudo().search([], order="model"):  # pylint: disable=no-search-all
            model = record.model
            if self._ai_is_queryable_model(model) and self.env[model].has_access(
                "read"
            ):
                result.append({"model": model, "name": record.name})
        return {"models": result}

    @aitool(
        input_schema={"model": {"type": "string"}},
        required_inputs=["model"],
        output_schema={
            "fields": {"type": "object", "additionalProperties": True},
            "hidden": {"type": "array", "items": {"type": "string"}},
        },
    )
    def _ai_get_fields(self, model):
        """Describe the readable fields of ``model``, and list under ``hidden``
        the fields forbidden to AI. A field the caller could not see anyway
        (``groups=``) is not listed, so as not to disclose it."""
        target = self._ai_target(model)
        readable = self._ai_readable_field_names(model)
        forbidden = self._ai_forbidden_fields()
        meta = target.fields_get(
            attributes=["string", "help", "type", "selection", "relation", "required"]
        )
        return {
            "fields": {name: info for name, info in meta.items() if name in readable},
            # fields_get() also lists virtual fields (res.users' sel_groups_*).
            # Reporting forbidden fields under ``hidden`` is deliberate: it
            # tells the agent they exist but are off-limits, unlike
            # group-restricted fields which are not disclosed at all.
            "hidden": sorted(
                name for name in meta if target._fields.get(name) in forbidden
            ),
        }

    @aitool(
        input_schema={
            "model": {"type": "string"},
            "domain": {"type": "array"},
            "fields": {"type": "array", "items": {"type": "string"}},
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT},
            "offset": {"type": "integer", "minimum": 0},
            "order": {"type": "string"},
        },
        required_inputs=["model"],
        output_schema={
            "records": {
                "type": "array",
                "items": {"type": "object", "additionalProperties": True},
            },
            "has_more": {"type": "boolean"},
            "total_count": {"type": "integer"},
            "inaccessible_fields": {"type": "array", "items": {"type": "string"}},
        },
    )
    def _ai_search_read(
        self, model, domain=None, fields=None, limit=MAX_LIMIT, offset=0, order=None
    ):
        """Search and read records of ``model`` with the caller's rights.

        Only readable fields are returned, the stored ones unless ``fields`` is
        given, which keeps the default read clear of computations that may fail
        for the caller; fields refused at read time are listed in
        ``inaccessible_fields`` (:meth:`_ai_read`). Many2one values are plain
        IDs (``load=None``): the display name core would add is built from the
        related record's fields, which may be forbidden there. ``has_more``
        tells whether a next page exists, read with ``offset`` under the same
        domain and order, and ``total_count`` how many records match in all,
        so that an agent need not page through them to count.
        """
        target = self._ai_target(model)
        readable = self._ai_readable_field_names(model)
        if fields is None:
            output_fields = [name for name in readable if target._fields[name].store]
        else:
            # An explicit empty list asks for ids only, not the defaults.
            output_fields = [name for name in fields if name in readable]
        # The schema bounds are not enforced by the caller (ai_oca_mcp passes the
        # arguments through). Odoo reads every record for a limit of 0 or less,
        # past the cap, and agents send -1 to mean "all": cap those too.
        if not limit or limit < 1 or limit > MAX_LIMIT:
            limit = MAX_LIMIT
        # One record past the page tells whether there is a next one.
        records = target.search(
            domain or [], offset=offset, limit=limit + 1, order=order
        )
        # Never read an empty list: Odoo reads *all* fields for it. ``id`` comes
        # with every row anyway.
        rows, inaccessible_fields = self._ai_read(
            records[:limit], output_fields or ["id"]
        )
        return {
            "records": [self._ai_jsonify(row) for row in rows],
            "has_more": len(records) > limit,
            "total_count": target.search_count(domain or []),
            "inaccessible_fields": inaccessible_fields,
        }

    def _ai_check_groupable(self, model, field_name, readable):
        """Refuse to group or aggregate on a field the tools may not return,
        or on one the database cannot group by (not stored)."""
        field = self.env[model]._fields.get(field_name)
        if not field or field_name not in readable:
            raise UserError(
                self.env._(
                    "Field '%(field)s' of model '%(model)s' does not exist or "
                    "cannot be read.",
                    field=field_name,
                    model=model,
                )
            )
        if not field.store:
            raise UserError(
                self.env._(
                    "Field '%(field)s' of model '%(model)s' is not stored: it "
                    "cannot be grouped or aggregated.",
                    field=field_name,
                    model=model,
                )
            )

    def _ai_group_value(self, value):
        """Make a ``_read_group`` value JSON-serializable: a record becomes its
        ID (False for none), as search_read returns relational fields, and a
        date its ISO string."""
        if isinstance(value, models.BaseModel):
            return value.id or False
        if isinstance(value, date):
            return value.isoformat()
        return value

    @aitool(
        input_schema={
            "model": {"type": "string"},
            "domain": {"type": "array"},
        },
        required_inputs=["model"],
        output_schema={
            "count": {"type": "integer"},
        },
    )
    def _ai_search_count(self, model, domain=None):
        """Count the records of ``model`` matching ``domain``, with the
        caller's rights, without reading them."""
        target = self._ai_target(model)
        return {"count": target.search_count(domain or [])}

    @aitool(
        input_schema={
            "model": {"type": "string"},
            "domain": {"type": "array"},
            "groupby": {"type": "array", "items": {"type": "string"}},
            "aggregates": {"type": "array", "items": {"type": "string"}},
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_GROUP_LIMIT},
            "offset": {"type": "integer", "minimum": 0},
            "order": {"type": "string"},
        },
        required_inputs=["model"],
        output_schema={
            "groups": {
                "type": "array",
                "items": {"type": "object", "additionalProperties": True},
            },
            "has_more": {"type": "boolean"},
        },
    )
    def _ai_read_group(
        self,
        model,
        domain=None,
        groupby=None,
        aggregates=None,
        limit=DEFAULT_GROUP_LIMIT,
        offset=0,
        order=None,
    ):
        """Group the records of ``model`` matching ``domain`` and aggregate
        their values, with the caller's rights.

        ``groupby`` takes field names, with a date granularity for date fields
        (``date_order:month``). ``aggregates`` takes ``field:function`` specs
        and ``__count``, the default. Only fields the tools may return can be
        grouped or aggregated: a forbidden field would show its values in the
        group keys. Each group is an object keyed by the given specs; records
        are their IDs, dates ISO strings. ``has_more`` tells whether a next page
        of groups exists, read with ``offset`` under the same arguments.
        """
        target = self._ai_target(model)
        readable = self._ai_readable_field_names(model)
        groupby = list(groupby or [])
        aggregates = list(aggregates or ["__count"])
        for spec in groupby:
            self._ai_check_groupable(model, spec.partition(":")[0], readable)
        for spec in aggregates:
            if spec == "__count":
                continue
            field_name, _sep, function = spec.partition(":")
            if function not in AGGREGATE_FUNCTIONS:
                raise UserError(
                    self.env._(
                        "Aggregate '%(spec)s' is not supported: use "
                        "'field:function' with one of %(functions)s, or '__count'.",
                        spec=spec,
                        functions=", ".join(AGGREGATE_FUNCTIONS),
                    )
                )
            self._ai_check_groupable(model, field_name, readable)
        specs = groupby + aggregates
        # The ORM also sorts groups by an aggregate left out of the specs,
        # which could be one on a forbidden field: keep the order to the specs.
        for order_part in (order or "").split(","):
            term = order_part.split()[0] if order_part.strip() else None
            if term and term not in specs:
                raise UserError(
                    self.env._(
                        "Order term '%(term)s' must be one of the groupby or "
                        "aggregates specs.",
                        term=term,
                    )
                )
        # As in search_read, the schema bounds are not enforced by the caller.
        if not limit or limit < 1 or limit > MAX_GROUP_LIMIT:
            limit = MAX_GROUP_LIMIT
        try:
            # One group past the page tells whether there is a next one.
            rows = target._read_group(
                domain or [],
                groupby,
                aggregates,
                offset=offset or 0,
                limit=limit + 1,
                order=order or None,
            )
        except ValueError as e:
            # An unknown granularity or an order not on a spec: the agent can
            # correct the call from the message.
            raise UserError(str(e)) from e
        return {
            "groups": [
                {
                    spec: self._ai_group_value(value)
                    for spec, value in zip(specs, row, strict=True)
                }
                for row in rows[:limit]
            ],
            "has_more": len(rows) > limit,
        }
