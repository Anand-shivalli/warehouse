"""RoHS candidate records: list, verify (with optional corrections), reject. A human compliance reviewer is the only
way a record becomes 'Verified'. Every action is written to the audit log."""
from psycopg.types.json import Jsonb

import db
import incident_store as store

EDITABLE = ("supplier", "part_number", "product_scope", "declaration_date", "valid_until", "exemptions")
LIST_SQL = ("SELECT r.rohs_record_id, d.document_id, d.revision, d.title AS document_title, r.supplier, r.part_number, r.product_scope, "
            "r.declaration_date, r.valid_until, r.exemptions, r.source_page, r.source_excerpt, r.extraction_confidence, r.field_confidence, "
            "r.validation_status, r.verified_by, r.verified_at, r.review_note FROM rohs_records r JOIN documents d ON d.id = r.doc_id")


def list_records(status=None, document_id=None):
    sql, args, where = LIST_SQL, [], []
    if status:
        where.append("r.validation_status = %s"); args.append(status)
    if document_id:
        where.append("d.document_id = %s"); args.append(document_id)
    if where:
        sql += " WHERE " + " AND ".join(where)
    with db.conn() as c:
        return [store.clean(r) for r in c.execute(sql + " ORDER BY r.rohs_record_id", args).fetchall()]


def _get(c, rid):
    r = c.execute(LIST_SQL + " WHERE r.rohs_record_id = %s FOR UPDATE OF r", (rid,)).fetchone()
    if not r:
        raise store.StoreError("RoHS record not found", 404)
    return r


def verify(rid, actor, edits=None, note=None, role=None):
    edits = {k: v for k, v in (edits or {}).items() if k in EDITABLE and v is not None}
    with db.conn() as c:
        r = _get(c, rid)
        if r["validation_status"] == "Verified" and not edits:
            raise store.StoreError("Already verified.", 409)
        new = dict(r)
        for k, v in edits.items():
            if k in ("declaration_date", "valid_until"):
                v = store.parse_day(v, k)
            elif k == "exemptions":
                if not isinstance(v, list):
                    raise store.StoreError("exemptions must be a list of strings.", 422)
                v = [str(x) for x in v]
            elif isinstance(v, str):
                v = v.strip() or None
            new[k] = v
        missing = [k for k in ("supplier", "part_number", "declaration_date") if not new.get(k)]
        if missing:
            raise store.StoreError(f"Cannot verify: {', '.join(missing)} must be filled in (correct them in the request).", 422)
        c.execute("UPDATE rohs_records SET supplier=%s, part_number=%s, product_scope=%s, declaration_date=%s, valid_until=%s, exemptions=%s, "
                  "validation_status='Verified', verified_by=%s, verified_at=now(), review_note=%s WHERE rohs_record_id=%s",
                  (new["supplier"], new["part_number"], new["product_scope"], new["declaration_date"], new["valid_until"],
                   Jsonb(new["exemptions"]),
                   actor, note, rid))
        changed = sorted(k for k in edits if edits[k] != r.get(k))
        store.audit(actor, "RoHS record verified", f"{r['document_id']}@{r['revision']} record {rid}" + (f"; corrected: {', '.join(changed)}" if changed else ""),
                    role=role, entity_id=f"rohs:{rid}", conn=c)
    return get(rid)


def reject(rid, actor, note, role=None):
    if not (note or "").strip():
        raise store.StoreError("A note is required to reject a RoHS record.", 400)
    with db.conn() as c:
        r = _get(c, rid)
        c.execute("UPDATE rohs_records SET validation_status='Rejected', verified_by=%s, verified_at=now(), review_note=%s WHERE rohs_record_id=%s",
                  (actor, note, rid))
        store.audit(actor, "RoHS record rejected", f"{r['document_id']}@{r['revision']} record {rid}: {note[:200]}", role=role, entity_id=f"rohs:{rid}", conn=c)
    return get(rid)


def get(rid):
    with db.conn() as c:
        r = c.execute(LIST_SQL + " WHERE r.rohs_record_id = %s", (rid,)).fetchone()
    if not r:
        raise store.StoreError("RoHS record not found", 404)
    return store.clean(r)
