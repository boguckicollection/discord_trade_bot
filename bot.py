import os
import csv
import discord
from discord.ext import commands
from discord.ui import Modal, TextInput, View, Select
from datetime import datetime, timedelta
import asyncio
from dotenv import load_dotenv
from streaming import write_auction_html, STREAMING_ENABLED, html_export_dir

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

forum_channel_id = int(os.environ["FORUM_CHANNEL_ID"])
command_channel_id = os.environ.get("COMMAND_CHANNEL_ID")
if command_channel_id:
    command_channel_id = int(command_channel_id)
active_auctions = {}  # message_id: {...}

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


async def create_auction(author, title, desc, price, increment, minutes, image_url=None):
    end_time = datetime.utcnow() + timedelta(minutes=minutes)

    embed = discord.Embed(
        title=f"📈 {title}",
        description=desc,
        color=discord.Color.orange(),
    )
    embed.add_field(name="Cena początkowa", value=f"{price:.2f} zł")
    embed.add_field(name="Kwota przebicia", value=f"{increment:.2f} zł")
    if image_url:
        embed.set_image(url=image_url)
    embed.set_footer(text=f"Koniec licytacji za {minutes} minut")

    forum_channel = bot.get_channel(forum_channel_id)
    if not forum_channel:
        raise RuntimeError("Nie znaleziono kanału Forum")

    thread_kwargs = {
        "name": title,
        "content": "Nowa licytacja!",
        "embed": embed,
    }
    if forum_channel.available_tags:
        thread_kwargs["applied_tags"] = [forum_channel.available_tags[0]]

    post = await forum_channel.create_thread(**thread_kwargs)
    message = await post.send(embed=embed)
    await message.add_reaction("🔼")

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
        "html_file": os.path.join(html_export_dir, f"auction_{message.id}.html") if STREAMING_ENABLED else None,
        "image_url": image_url,
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
        await interaction.response.send_message("Prześlij teraz zdjęcie lub wpisz 'pomiń'", ephemeral=True)

        def check(msg: discord.Message):
            return msg.author.id == interaction.user.id and msg.channel == interaction.channel

        image_url = None
        try:
            msg = await bot.wait_for("message", check=check, timeout=120)
            if msg.attachments:
                image_url = msg.attachments[0].url
            elif msg.content.lower().strip() == "pomiń":
                image_url = None
            else:
                image_url = None
        except asyncio.TimeoutError:
            pass

        await create_auction(
            author=self.author,
            title=self.title_input.value,
            desc=self.desc_input.value,
            price=price,
            increment=increment,
            minutes=minutes,
            image_url=image_url,
        )

        await interaction.followup.send("Licytacja utworzona!", ephemeral=True)


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

@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return
    if reaction.message.id not in active_auctions:
        return
    if str(reaction.emoji) != "🔼":
        return
    auction = active_auctions[reaction.message.id]
    new_price = auction["price"] + auction["increment"]
    auction["price"] = new_price
    auction["leader_id"] = user.id
    auction["leader_name"] = user.display_name
    embed = reaction.message.embeds[0]
    embed.set_field_at(0, name="Aktualna cena", value=f"{new_price:.2f} zł", inline=False)
    embed.set_footer(text=f"Najwyższa oferta: {user.display_name}")
    await reaction.message.edit(embed=embed)
    write_auction_html(auction)
    await reaction.message.channel.send(f"{user.mention} podbija cenę do {new_price:.2f} zł!")
    await reaction.remove(user)

# Komenda do uruchomienia kolejnej pozycji z listy
@bot.command()
async def start_next(ctx):
    if command_channel_id and ctx.channel.id != command_channel_id:
        await ctx.send(f"Ta komenda jest dostępna tylko na kanale <#{command_channel_id}>.")
        return
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
        image_url=None,
    )
    await ctx.send(f"Licytacja '{item['title']}' rozpoczęta.")

# Komenda do uruchomienia ogłoszenia
@bot.command()
async def ogłoszenie(ctx):
    if command_channel_id and ctx.channel.id != command_channel_id:
        await ctx.send(f"Ta komenda jest dostępna tylko na kanale <#{command_channel_id}>.")
        return
    options = [
        discord.SelectOption(label="Licytacja", value="licytacja", emoji="📈"),
        discord.SelectOption(label="Sprzedaż", value="sprzedaz", emoji="💰"),
        discord.SelectOption(label="Wymiana", value="wymiana", emoji="🔁"),
        discord.SelectOption(label="Szukam/kupno", value="kupno", emoji="🔍"),
    ]

    class OgłoszenieView(View):
        @discord.ui.select(placeholder="Wybierz typ ogłoszenia", options=options)
        async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
            if select.values[0] == "licytacja":
                await interaction.response.send_modal(AuctionModal(author=interaction.user))
            else:
                await interaction.response.send_message("Ten typ ogłoszenia jeszcze nieobsługiwany.", ephemeral=True)

    await ctx.send("Wybierz typ ogłoszenia:", view=OgłoszenieView())

bot.run(os.environ["DISCORD_TOKEN"])
