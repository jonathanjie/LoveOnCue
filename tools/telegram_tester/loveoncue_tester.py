"""Drive the LoveOnCue Telegram bot from a real user account for staging tests.

This tool uses Telegram's user API (MTProto) through Telethon. A logged-in
session can act as the whole account, so the tool limits itself to one chat:
it resolves the configured bot username, checks that the peer is a bot, and
never lists or opens other dialogs.

Commands:
    login               One-time interactive login. A person types the code.
    send TEXT           Send TEXT to the bot and print its replies.
    tap LABEL           Press the callback button LABEL on the newest bot
                        message that has it, then print the replies.
    history [COUNT]     Print the last COUNT messages in the bot chat.
    photo [PATH]        Send a photo (default: a generated test card) and
                        print the replies. Use --caption to add text.
    whoami              Print the numeric Telegram user ID of the session.

Configuration lives in a root-only directory (default /etc/loveoncue-tester):
    config.env      LOVEONCUE_TESTER_API_ID and LOVEONCUE_TESTER_API_HASH
    user.session    The Telethon session created by `login`
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import stat
import struct
import sys
import tempfile
import time
import zlib
from pathlib import Path

from telethon import TelegramClient
from telethon.tl.custom.message import Message
from telethon.tl.types import InlineButtonTypeCallback, User

DEFAULT_CONFIG_DIR = Path("/etc/loveoncue-tester")
DEFAULT_BOT_USERNAME = "LoveOnCue_bot"

# The bot replies through a durable outbox, so a reply can take a few seconds.
REPLY_TIMEOUT_SECONDS = 25.0
# Stop waiting once no new bot message has arrived for this long.
REPLY_QUIET_SECONDS = 4.0
POLL_INTERVAL_SECONDS = 1.0


# Size of the generated test card. Telegram rejects very small photos.
SAMPLE_WIDTH, SAMPLE_HEIGHT = 480, 320
# Wide vertical stripes, so a vision model has something plain to describe.
SAMPLE_STRIPES = [(196, 64, 64), (240, 200, 80), (72, 150, 96), (64, 110, 190), (240, 240, 240)]


class TesterError(Exception):
    """A problem the operator can fix, reported without a traceback."""


def read_config(config_dir: Path) -> tuple[int, str]:
    config_file = config_dir / "config.env"
    if not config_file.exists():
        raise TesterError(f"{config_file} is missing. Run the login command first.")
    values = {}
    for line in config_file.read_text().splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value.strip()
    try:
        return int(values["LOVEONCUE_TESTER_API_ID"]), values["LOVEONCUE_TESTER_API_HASH"]
    except (KeyError, ValueError):
        raise TesterError(f"{config_file} needs LOVEONCUE_TESTER_API_ID and LOVEONCUE_TESTER_API_HASH.") from None


def write_private_file(path: Path, text: str) -> None:
    """Create or replace a file that only its owner can read."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(text)


def prompt_for_config(config_dir: Path) -> None:
    print("Create an app at https://my.telegram.org/apps, then enter its values.")
    api_id = input("API ID: ").strip()
    if not api_id.isdecimal():
        raise TesterError("The API ID must be a number.")
    api_hash = getpass.getpass("API hash (hidden): ").strip()
    if len(api_hash) != 32:
        raise TesterError("The API hash must be 32 characters.")
    write_private_file(
        config_dir / "config.env",
        f"LOVEONCUE_TESTER_API_ID={api_id}\nLOVEONCUE_TESTER_API_HASH={api_hash}\n",
    )


def sample_png() -> bytes:
    """Build a small striped PNG with the standard library only."""
    stripe_width = SAMPLE_WIDTH // len(SAMPLE_STRIPES)
    pixels = b"".join(bytes(SAMPLE_STRIPES[min(x // stripe_width, len(SAMPLE_STRIPES) - 1)])
                      for x in range(SAMPLE_WIDTH))
    # Each PNG row starts with filter type 0 (no filter).
    raw = b"".join(b"\x00" + pixels for _ in range(SAMPLE_HEIGHT))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", SAMPLE_WIDTH, SAMPLE_HEIGHT, 8, 2, 0, 0, 0)  # 8-bit RGB
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


async def send_photo(client: TelegramClient, bot: User, path: Path | None, caption: str) -> None:
    if path is not None:
        if not path.is_file():
            raise TesterError(f"{path} is not a file.")
        await client.send_file(bot, str(path), caption=caption or None)
        return
    with tempfile.NamedTemporaryFile(suffix=".png") as handle:
        handle.write(sample_png())
        handle.flush()
        await client.send_file(bot, handle.name, caption=caption or None, force_document=False)


def make_client(config_dir: Path) -> TelegramClient:
    api_id, api_hash = read_config(config_dir)
    # Telethon appends ".session" to this path.
    return TelegramClient(str(config_dir / "user"), api_id, api_hash)


async def resolve_bot(client: TelegramClient, username: str) -> User:
    entity = await client.get_entity(username)
    if not isinstance(entity, User) or not entity.bot:
        raise TesterError(f"@{username} is not a bot. Refusing to use this chat.")
    if (entity.username or "").lower() != username.lower():
        raise TesterError(f"@{username} resolved to a different account.")
    return entity


def is_callback(button) -> bool:
    """True for inline buttons that send data to the bot, not links or Mini Apps."""
    return isinstance(button.button.type, InlineButtonTypeCallback)


def describe(message: Message) -> str:
    sender = "you" if message.out else "bot"
    lines = [f"[{message.id}] {sender}: {message.text or '<no text>'}"]
    for row in message.buttons or []:
        labels = []
        for button in row:
            kind = "" if is_callback(button) else " (link)"
            labels.append(f"[{button.text}{kind}]")
        lines.append("    " + " ".join(labels))
    return "\n".join(lines)


async def newest_message_id(client: TelegramClient, bot: User) -> int:
    messages = await client.get_messages(bot, limit=1)
    return messages[0].id if messages else 0


async def wait_for_replies(client: TelegramClient, bot: User, after_id: int) -> list[Message]:
    """Collect bot messages newer than after_id until the chat goes quiet."""
    replies: dict[int, Message] = {}
    started = time.monotonic()
    last_arrival = None
    while time.monotonic() - started < REPLY_TIMEOUT_SECONDS:
        for message in await client.get_messages(bot, min_id=after_id, limit=20):
            if not message.out:
                if message.id not in replies:
                    last_arrival = time.monotonic()
                # Keep the newest copy, because the bot can edit a message.
                replies[message.id] = message
        if last_arrival is not None and time.monotonic() - last_arrival >= REPLY_QUIET_SECONDS:
            break
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
    return [replies[ident] for ident in sorted(replies)]


def print_replies(replies: list[Message]) -> None:
    if not replies:
        print(f"No bot reply within {REPLY_TIMEOUT_SECONDS:.0f} seconds.")
    for message in replies:
        print(describe(message))


async def find_callback_button(client: TelegramClient, bot: User, label: str):
    """Return the newest bot message and the callback button with this label."""
    async for message in client.iter_messages(bot, limit=30):
        if message.out:
            continue
        for row in message.buttons or []:
            for button in row:
                if button.text.strip().lower() == label.strip().lower():
                    if not is_callback(button):
                        raise TesterError(f"[{button.text}] opens a link or Mini App. Only callback buttons are pressed.")
                    return message, button
    raise TesterError(f"No recent bot message has a [{label}] button.")


async def run_login(config_dir: Path, username: str) -> None:
    config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not (config_dir / "config.env").exists():
        prompt_for_config(config_dir)
    client = make_client(config_dir)
    # start() asks for the phone number, the login code, and any 2FA password.
    await client.start()
    try:
        me = await client.get_me()
        bot = await resolve_bot(client, username)
        os.chmod(config_dir / "user.session", stat.S_IRUSR | stat.S_IWUSR)
        print(f"Logged in as user {me.id}. Test chat: @{bot.username}.")
    finally:
        await client.disconnect()


async def run_command(args: argparse.Namespace) -> None:
    client = make_client(args.config_dir)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise TesterError("The session is not logged in. Run the login command first.")
        if args.command == "whoami":
            print((await client.get_me()).id)
            return
        bot = await resolve_bot(client, args.bot)
        if args.command == "history":
            messages = await client.get_messages(bot, limit=args.count)
            for message in reversed(messages):
                print(describe(message))
            return
        before = await newest_message_id(client, bot)
        if args.command == "send":
            await client.send_message(bot, args.text)
        elif args.command == "photo":
            await send_photo(client, bot, args.path, args.caption)
            print("Sent photo.")
        else:
            message, button = await find_callback_button(client, bot, args.label)
            answer = await button.click()
            toast = getattr(answer, "message", None)
            print(f"Pressed [{button.text}] on message {message.id}." + (f" Toast: {toast}" if toast else ""))
        print_replies(await wait_for_replies(client, bot, before))
    finally:
        await client.disconnect()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test the LoveOnCue bot from a real Telegram user account.")
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--bot", default=DEFAULT_BOT_USERNAME, help="Bot username without @.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("login", help="Log in once, interactively.")
    send = commands.add_parser("send", help="Send a message and print the replies.")
    send.add_argument("text")
    tap = commands.add_parser("tap", help="Press a callback button and print the replies.")
    tap.add_argument("label")
    history = commands.add_parser("history", help="Print recent messages in the bot chat.")
    history.add_argument("count", nargs="?", type=int, default=10)
    photo = commands.add_parser("photo", help="Send a photo and print the replies.")
    photo.add_argument("path", nargs="?", type=Path, help="Image file. Default: a generated test card.")
    photo.add_argument("--caption", default="")
    commands.add_parser("whoami", help="Print the session's Telegram user ID.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        if args.command == "login":
            asyncio.run(run_login(args.config_dir, args.bot))
        else:
            asyncio.run(run_command(args))
    except TesterError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
