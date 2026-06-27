# Task 8: "Cetak Semua" UI Section

**Files:**
- Modify: `ui/pages/update_price.py`

**Goal:** Add persistent session UI showing pending tag count, Cetak Semua download/print, and Hapus Sesi.

## Changes

### 1. Add `_render_tag_session_ui` function after `_clear_tag_session`

```python
def _render_tag_session_ui():
    """Show persistent session UI for accumulated price tags.

    Visible whenever price_tag_items is non-empty.
    Shows count, Cetak Semua button, and Clear button.
    """
    count = _tag_session_count()
    if count == 0:
        return

    st.markdown("---")
    st.subheader(f"🏷️ Price Tag Sesi ({count} label)")

    with st.spinner("🔄 Membuat PDF..."):
        tag_service = PriceTagService()
        try:
            pdf_bytes = tag_service.generate_pdf(
                st.session_state.price_tag_items, size_preset="standard"
            )
        except Exception as e:
            st.error(f"Gagal generate PDF: {e}")
            return

    col_pdf, col_print, col_clear = st.columns([1, 1, 1])
    with col_pdf:
        st.download_button(
            "⬇️ Download PDF (A4 48x30mm)",
            data=pdf_bytes,
            file_name="label_kenaikan_sesi.pdf",
            mime="application/pdf",
            type="primary",
            use_container_width=True,
        )
    with col_print:
        if st.button("🖨️ Print di Browser", use_container_width=True):
            import base64
            import streamlit.components.v1 as components
            pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
            components.html(
                f"""<script>
                  (function(){{
                    try {{
                      const bytes = Uint8Array.from(atob("{pdf_b64}"), c=>c.charCodeAt(0));
                      const url = URL.createObjectURL(new Blob([bytes],{{type:'application/pdf'}}));
                      const w = window.open(url,'_blank');
                      if(!w){{ alert('Popup blocked.'); return; }}
                      const t = setInterval(()=>{{
                        try{{ if(w.document.readyState==='complete'){{ clearInterval(t); w.focus(); w.print(); }} }}
                        catch(e){{}}
                      }},250);
                    }}catch(e){{ alert('Failed: '+(e.message||e)); }}
                  }})();
                </script>""",
                height=0,
            )
    with col_clear:
        if st.button("🗑️ Hapus Sesi", type="secondary", use_container_width=True):
            _clear_tag_session()
            st.rerun()

    with st.expander("🔥 Thermal Label (28x18mm)", expanded=False):
        try:
            thermal_bytes = tag_service.generate_thermal_labels_pdf(
                st.session_state.price_tag_items, width_mm=28.0, height_mm=18.0
            )
            st.download_button(
                "⬇️ Download Thermal PDF",
                data=thermal_bytes,
                file_name="thermal_kenaikan_sesi.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as e:
            st.warning(f"Thermal PDF gagal: {e}")
```

### 2. Call `_render_tag_session_ui` at end of `render_update_price_page()`

Add before the final `if "analysis_rows"` check or after `_render_analysis()`:

```python
# ── Step 4: Price tag session UI ───────────────────────────────────
_render_tag_session_ui()
```

### 3. Run tests

Run: `python -m pytest tests/test_price_tag_session.py -v`
Expected: PASS (existing 5 tests)

### 4. Commit

```
git add ui/pages/update_price.py
git commit -m "feat: add persistent cetak semua section with session UI"
```
