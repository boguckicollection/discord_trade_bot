import discord
from discord.ext import commands, tasks
from discord.ui import Modal, TextInput, View, Button, Select
from datetime import datetime, timedelta
import asyncio

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

forum_channel_id = 123456789012345678  # Zmień na ID Twojego kanału-forum
active_auctions = {}  # message_id: {...}

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

        end_time = datetime.utcnow() + timedelta(minutes=minutes)

        embed = discord.Embed(
            title=f"📈 {self.title_input.value}",
            description=self.desc_input.value,
            color=discord.Color.orange()
        )
        embed.add_field(name="Cena początkowa", value=f"{price:.2f} zł")
        embed.add_field(name="Kwota przebicia", value=f"{increment:.2f} zł")
        embed.set_footer(text=f"Koniec licytacji za {minutes} minut")

        forum_channel = bot.get_channel(forum_channel_id)
        if not forum_channel:
            await interaction.response.send_message("Nie znaleziono kanału Forum.", ephemeral=True)
            return

        post = await forum_channel.create_thread(name=self.title_input.value, content="Nowa licytacja!", embed=embed)
        message = await post.send(embed=embed, view=BidButton())

        # Zapisz dane licytacji
        active_auctions[message.id] = {
            "author_id": self.author.id,
            "price": price,
            "increment": increment,
            "leader_id": None,
            "end_time": end_time,
            "thread": post,
            "message": message
        }

        await interaction.response.send_message("Licytacja utworzona!", ephemeral=True)

        # Automatyczne zakończenie licytacji
        bot.loop.create_task(end_auction_after(message.id, minutes * 60))

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

        embed = interaction.message.embeds[0]
        embed.set_field_at(0, name="Aktualna cena", value=f"{new_price:.2f} zł", inline=False)
        embed.set_footer(text=f"Najwyższa oferta: {interaction.user.display_name}")

        await interaction.message.edit(embed=embed, view=self)
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

bot.run("YOUR_TOKEN")
