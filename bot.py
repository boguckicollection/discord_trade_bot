import os
import csv
import discord
from discord.ext import commands
from discord.ui import Modal, TextInput, View, Button
from datetime import datetime, timedelta
import asyncio

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

forum_channel_id = int(os.environ["FORUM_CHANNEL_ID"])
active_auctions = {}  # message_id: {...}
html_export_dir = os.environ.get("HTML_EXPORT_DIR", "exports")
os.makedirs(html_export_dir, exist_ok=True)

auction_queue = []
items_file = os.environ.get("AUCTION_ITEMS_FILE", "auction_items.csv")
if os.path.exists(items_file):
    with open(items_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                auction_queue.append(
                    {
                        "title": row["title"],
                        "description": row.get("description", ""),
                        "start_price": float(row["start_price"]),
                        "increment": float(row["increment"]),
                        "duration": int(row["duration"]),
                    }
                )
            except (KeyError, ValueError):
                continue


def write_auction_html(auction):
    path = auction.get("html_file")
    if not path:
        return
    leader = auction.get("leader_name") or "Brak ofert"
    end_iso = auction["end_time"].isoformat()
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
<div class='price' id='price'>{auction['price']:.2f} zł</div>
<p>Najwyższa oferta: {leader}</p>
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


async def create_auction(author, title, desc, price, increment, minutes):
    end_time = datetime.utcnow() + timedelta(minutes=minutes)

    embed = discord.Embed(
        title=f"📈 {title}",
        description=desc,
        color=discord.Color.orange(),
    )
    embed.add_field(name="Cena początkowa", value=f"{price:.2f} zł")
    embed.add_field(name="Kwota przebicia", value=f"{increment:.2f} zł")
    embed.set_footer(text=f"Koniec licytacji za {minutes} minut")

    forum_channel = bot.get_channel(forum_channel_id)
    if not forum_channel:
        raise RuntimeError("Nie znaleziono kanału Forum")

    post = await forum_channel.create_thread(name=title, content="Nowa licytacja!", embed=embed)
    message = await post.send(embed=embed, view=BidButton())

    auction = {
        "author_id": author.id,
        "price": price,
        "increment": increment,
        "leader_id": None,
        "leader_name": None,
        "end_time": end_time,
        "thread": post,
        "message": message,
        "title": title,
        "description": desc,
        "html_file": os.path.join(html_export_dir, f"auction_{message.id}.html"),
    }
    active_auctions[message.id] = auction
    write_auction_html(auction)
    bot.loop.create_task(end_auction_after(message.id, minutes * 60))
    return message

class AuctionModal(Modal, title="Nowa Licytacja"):
    def __init__(self, author):
        super().__init__()
        self.author = author

        self.title_input = TextInput(label="Tytuł", required=True, max_length=100)
        self.desc_input = TextInput(label="Opis", style=discord.TextStyle.paragraph, required=True)
        self.start_price = TextInput(label="Cena początkowa (zł)", required=True)
        self.increment = TextInput(label="Kwota przebicia (zł)", required=True)
        self.duration = TextInput(label="Czas trwania (minuty)", required=True)

        self.add_item(self.title_input)
        self.add_item(self.desc_input)
        self.add_item(self.start_price)
        self.add_item(self.increment)
        self.add_item(self.duration)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price = float(self.start_price.value.replace(",", "."))
            increment = float(self.increment.value.replace(",", "."))
            minutes = int(self.duration.value)
        except ValueError:
            await interaction.response.send_message("Błąd: Cena i czas muszą być liczbami.", ephemeral=True)
            return

        await create_auction(
            author=self.author,
            title=self.title_input.value,
            desc=self.desc_input.value,
            price=price,
            increment=increment,
            minutes=minutes,
        )

        await interaction.response.send_message("Licytacja utworzona!", ephemeral=True)

class BidButton(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Button(label="🔼 Przebij", custom_id="bid"))

    @discord.ui.button(label="🔼 Przebij", style=discord.ButtonStyle.green, custom_id="bid")
    async def bid(self, interaction: discord.Interaction, button: Button):
        auction = active_auctions.get(interaction.message.id)
        if not auction:
            await interaction.response.send_message("Licytacja zakończona lub nieznaleziona.", ephemeral=True)
            return

        new_price = auction["price"] + auction["increment"]
        auction["price"] = new_price
        auction["leader_id"] = interaction.user.id
        auction["leader_name"] = interaction.user.display_name

        embed = interaction.message.embeds[0]
        embed.set_field_at(0, name="Aktualna cena", value=f"{new_price:.2f} zł", inline=False)
        embed.set_footer(text=f"Najwyższa oferta: {interaction.user.display_name}")

        await interaction.message.edit(embed=embed, view=self)
        write_auction_html(auction)
        await interaction.response.send_message(f"✅ Przebiłeś licytację do {new_price:.2f} zł!", ephemeral=True)

async def end_auction_after(message_id, delay):
    await asyncio.sleep(delay)
    auction = active_auctions.pop(message_id, None)
    if not auction:
        return

    thread = auction["thread"]
    winner = f"<@{auction['leader_id']}>" if auction["leader_id"] else "Brak ofert"
    final_price = f"{auction['price']:.2f} zł"

    await thread.send(f"🏁 Licytacja zakończona!\nZwycięzca: {winner}\nKońcowa cena: {final_price}")
    await thread.edit(archived=True, locked=True)
    write_auction_html(auction)

# Komenda do uruchomienia kolejnej pozycji z listy
@bot.command()
async def start_next(ctx):
    if not auction_queue:
        await ctx.send("Brak kolejnych kart w pliku.")
        return
    item = auction_queue.pop(0)
    await create_auction(
        author=ctx.author,
        title=item["title"],
        desc=item["description"],
        price=item["start_price"],
        increment=item["increment"],
        minutes=item["duration"],
    )
    await ctx.send(f"Licytacja '{item['title']}' rozpoczęta.")

# Komenda do uruchomienia ogłoszenia
@bot.command()
async def ogłoszenie(ctx):
    options = [
        discord.SelectOption(label="Licytacja", value="licytacja", emoji="📈"),
        discord.SelectOption(label="Sprzedaż", value="sprzedaz", emoji="💰"),
        discord.SelectOption(label="Wymiana", value="wymiana", emoji="🔁"),
        discord.SelectOption(label="Szukam/kupno", value="kupno", emoji="🔍"),
    ]

    class OgłoszenieView(View):
        @discord.ui.select(placeholder="Wybierz typ ogłoszenia", options=options)
        async def select_callback(self, select, interaction: discord.Interaction):
            if select.values[0] == "licytacja":
                await interaction.response.send_modal(AuctionModal(author=interaction.user))
            else:
                await interaction.response.send_message("Ten typ ogłoszenia jeszcze nieobsługiwany.", ephemeral=True)

    await ctx.send("Wybierz typ ogłoszenia:", view=OgłoszenieView())

bot.run(os.environ["DISCORD_TOKEN"])
