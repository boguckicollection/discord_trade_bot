import os
from datetime import datetime

STREAMING_ENABLED = os.environ.get("ENABLE_STREAMING", "1") != "0"
html_export_dir = os.environ.get("HTML_EXPORT_DIR", "exports")
if STREAMING_ENABLED:
    os.makedirs(html_export_dir, exist_ok=True)


def write_auction_html(auction):
    if not STREAMING_ENABLED:
        return
    path = auction.get("html_file")
    if not path:
        return
    leader = auction.get("leader_name") or "Brak ofert"
    end_iso = auction["end_time"].isoformat()
    img_html = (
        f"<img src='{auction['image_url']}' style='max-width:100%'>" if auction.get("image_url") else ""
    )
    html = f"""
<html><head><meta charset='utf-8'>
<style>
body {{ font-family: Arial, sans-serif; }}
.price {{ font-size: 48px; color: red; }}
.flash {{ animation: flash 1s; }}
@keyframes flash {{ 0% {{opacity:0.5;}} 50% {{opacity:1;}} 100% {{opacity:0.5;}} }}
</style>
</head><body>
<h1>{auction['title']}</h1>
<p>{auction['description']}</p>
{img_html}
<div class='price' id='price'>{auction['price']:.2f} zł</div>
<p>Najwyższa oferta: {leader}</p>
<p>Liczba przebić: {auction['bid_count']}</p>
<p>Koniec licytacji za: <span id='timer'></span></p>
<script>
const end = new Date('{end_iso}');
function tick() {{
  const now = new Date();
  const diff = end - now;
  const m = Math.max(0, Math.floor(diff/60000));
  const s = Math.max(0, Math.floor((diff%60000)/1000));
  document.getElementById('timer').textContent = m + 'm ' + s + 's';
}}
setInterval(tick,1000);tick();
document.getElementById('price').classList.add('flash');
</script>
</body></html>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
