# Task 1: Fix `_query_mail_tracking()` — clean template IDs from result

**Files:**
- Modify: `logic/odoo_price_sync.py:424-461`

**Problem:** Template IDs (from `product.template` tracking entries) stay in the returned `result` dict alongside variant IDs. Caller at line 574 queries `product.product` with `("id", "in", product_ids)` — template IDs don't match any product.product → those products silently vanish from results.

**Fix:** After the template→variant mapping loop, remove template IDs from `result`.

### Step 1: Add cleanup after mapping loop

Locate lines 446-460 (the `if template_ids:` block). After the inner `for v in variants:` loop ends (after line 457), add:

```python
    # Remove template IDs — only variant IDs go to caller
    for tid in template_ids:
        result.pop(tid, None)
```

So the full block becomes:

```python
    if template_ids:
        try:
            variants = self.conn_mgr.search_read(
                "product.product",
                domain=[("product_tmpl_id", "in", list(template_ids))],
                fields=["id", "product_tmpl_id"],
            )
            for v in variants:
                vid = v["id"]
                ptid = v.get("product_tmpl_id")
                if isinstance(ptid, (list, tuple)) and ptid:
                    ptid = ptid[0]
                if ptid in result and vid not in result:
                    result[vid] = result[ptid]
        except Exception:
            pass

    # Remove template IDs — only variant IDs go to caller
    for tid in template_ids:
        result.pop(tid, None)

    return result
```

### Step 2: Run existing tests to confirm they still pass

```bash
cd D:\NKLabs\Streamlit && python -m pytest tests/test_odoo_price_sync.py -v
```

Expected: all existing tests pass.

### Report file
Write report to `.superpowers/sdd/task-1-report.md` with:
- Status: DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED
- Commits made (if any)
- Test output (full stdout)
- Any concerns
