#!/usr/bin/env python3
"""
Chess bot designed to beat the macOS Chess app at maximum difficulty.

The macOS Chess app uses Sjeng (~2000-2200 ELO at max difficulty).
This bot uses Stockfish at full strength (~3500+ ELO) — a decisive advantage.

Requirements:
    pip install python-chess
    brew install stockfish          # macOS
    sudo apt install stockfish      # Linux / Debian

Usage:
    # Play in the terminal (you enter moves, bot responds):
    python chess_bot.py

    # Bot plays White in terminal:
    python chess_bot.py --color white

    # Auto-play against macOS Chess (requires Accessibility permission):
    python chess_bot.py --mode auto

    # Suggest best moves while you play macOS Chess manually:
    python chess_bot.py --mode suggest

    # Tune thinking time and resources:
    python chess_bot.py --time 10 --threads 8 --hash 1024
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from typing import Optional

import chess
import chess.engine


# ─────────────────────────────────────────────────────────────────────────────
# Stockfish discovery
# ─────────────────────────────────────────────────────────────────────────────

_STOCKFISH_PATHS = [
    "/opt/homebrew/bin/stockfish",  # Homebrew — Apple Silicon
    "/usr/local/bin/stockfish",     # Homebrew — Intel Mac
    "/usr/bin/stockfish",           # Linux system package
    "stockfish",                    # Anywhere on PATH
]


def _find_stockfish() -> Optional[str]:
    for path in _STOCKFISH_PATHS:
        try:
            subprocess.run([path, "quit"], capture_output=True, timeout=3)
            return path
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Core chess engine
# ─────────────────────────────────────────────────────────────────────────────

class ChessBot:
    """
    Stockfish wrapper configured for maximum playing strength.

    Stockfish at Skill Level 20 with generous time/hash easily defeats
    macOS Chess (Sjeng engine) even at the highest computer level.
    """

    def __init__(
        self,
        stockfish_path: Optional[str] = None,
        think_time: float = 5.0,
        hash_mb: int = 512,
        threads: int = 4,
    ) -> None:
        self.think_time = think_time
        path = stockfish_path or _find_stockfish()
        if not path:
            sys.exit(
                "\nStockfish not found.\n"
                "  macOS:  brew install stockfish\n"
                "  Linux:  sudo apt install stockfish\n"
                "  Manual: https://stockfishchess.org/download/\n"
            )

        self.engine = chess.engine.SimpleEngine.popen_uci(path)
        self.board = chess.Board()

        # Maximum strength configuration
        self.engine.configure({
            "Skill Level": 20,    # 0–20; 20 is maximum
            "Hash": hash_mb,      # transposition table in MB
            "Threads": threads,   # parallel search threads
            "Move Overhead": 50,  # ms buffer to avoid time-outs
        })

    # ── Move generation ───────────────────────────────────────────────────────

    def best_move(self, time_limit: Optional[float] = None) -> chess.Move:
        """Return Stockfish's best move for the current position."""
        result = self.engine.play(
            self.board,
            chess.engine.Limit(time=time_limit or self.think_time),
        )
        return result.move  # type: ignore[return-value]

    def top_moves(self, n: int = 3) -> list[tuple[str, str]]:
        """Return the top *n* moves as [(SAN, eval_string)] pairs."""
        infos = self.engine.analyse(
            self.board,
            chess.engine.Limit(time=2.0),
            multipv=n,
        )
        results: list[tuple[str, str]] = []
        for info in infos:
            if "pv" not in info:
                continue
            move = info["pv"][0]
            san = self.board.san(move)
            score = info["score"].relative
            if score.is_mate():
                ev = f"M{score.mate()}"
            else:
                ev = f"{(score.score() or 0) / 100:+.2f}"
            results.append((san, ev))
        return results

    # ── Board manipulation ────────────────────────────────────────────────────

    def push_uci(self, uci: str) -> chess.Move:
        move = chess.Move.from_uci(uci)
        if move not in self.board.legal_moves:
            raise ValueError(f"Illegal move: {uci}")
        self.board.push(move)
        return move

    def push_san(self, san: str) -> chess.Move:
        move = self.board.parse_san(san)
        self.board.push(move)
        return move

    def apply_fen(self, fen: str) -> None:
        self.board.set_fen(fen)

    def reset(self) -> None:
        self.board = chess.Board()

    def undo(self) -> None:
        if self.board.move_stack:
            self.board.pop()

    # ── Status ────────────────────────────────────────────────────────────────

    @property
    def turn(self) -> str:
        return "White" if self.board.turn == chess.WHITE else "Black"

    @property
    def is_game_over(self) -> bool:
        return self.board.is_game_over()

    @property
    def outcome(self) -> Optional[chess.Outcome]:
        return self.board.outcome()

    def display(self) -> None:
        print()
        print(self.board)
        print(f"\nFEN  : {self.board.fen()}")
        print(f"Turn : {self.turn}  |  Move #{self.board.fullmove_number}")

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        self.engine.quit()

    def __enter__(self) -> "ChessBot":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


# ─────────────────────────────────────────────────────────────────────────────
# macOS Chess application interface
# ─────────────────────────────────────────────────────────────────────────────

def _applescript(script: str) -> str:
    """Run an AppleScript snippet and return its stdout, stripped."""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


class MacOSChessInterface:
    """
    Thin wrapper around the macOS Chess application via AppleScript.

    The Chess app ships with Sjeng as its engine.  At the highest difficulty
    Sjeng plays around 2000–2200 ELO.  Stockfish at max settings is ~3500+.

    AppleScript support in modern macOS Chess is limited; this class uses
    what is available and falls back gracefully when commands are unsupported.
    """

    def activate(self) -> None:
        _applescript('tell application "Chess" to activate')
        time.sleep(0.6)

    def is_running(self) -> bool:
        result = _applescript(
            'tell application "System Events"\n'
            '    return (name of processes) contains "Chess"\n'
            'end tell'
        )
        return result.lower() == "true"

    def new_game(self) -> None:
        """Open macOS Chess and start a new game (Cmd+N)."""
        _applescript('tell application "Chess" to activate')
        time.sleep(0.8)
        _applescript(
            'tell application "System Events"\n'
            '    tell process "Chess"\n'
            '        keystroke "n" using command down\n'
            '    end tell\n'
            'end tell'
        )
        time.sleep(1.0)

    def get_fen(self) -> Optional[str]:
        """
        Try to read the current board FEN from macOS Chess via AppleScript.
        Returns None if the app does not expose this property.
        """
        raw = _applescript(
            'tell application "Chess"\n'
            '    try\n'
            '        return fen\n'
            '    on error\n'
            '        return ""\n'
            '    end try\n'
            'end tell'
        )
        return raw if raw else None

    def make_move(self, uci: str) -> bool:
        """
        Attempt to play a move in macOS Chess using AppleScript.
        *uci* is a UCI-format string like "e2e4" or "g1f3".
        Returns True on apparent success.
        """
        src, dst = uci[:2], uci[2:4]
        result = _applescript(
            f'tell application "Chess"\n'
            f'    try\n'
            f'        move piece at "{src}" to "{dst}"\n'
            f'        return "ok"\n'
            f'    on error errMsg\n'
            f'        return errMsg\n'
            f'    end try\n'
            f'end tell'
        )
        return result == "ok"


# ─────────────────────────────────────────────────────────────────────────────
# Play modes
# ─────────────────────────────────────────────────────────────────────────────

_DIVIDER = "═" * 60


def _print_outcome(outcome: Optional[chess.Outcome]) -> None:
    if outcome is None:
        return
    if outcome.winner is None:
        print("\nGame over: Draw!")
    elif outcome.winner == chess.WHITE:
        print("\nGame over: White wins!")
    else:
        print("\nGame over: Black wins!")


def interactive_mode(bot: ChessBot, bot_plays: str = "black") -> None:
    """
    Terminal-based game.  You type moves; the bot replies.

    bot_plays: 'white' | 'black' | 'both'
    Move format: UCI (e2e4) or SAN (e4, Nf3, O-O).
    Commands: undo, reset, top, quit
    """
    print(f"\n{_DIVIDER}")
    print("  Chess Bot  ·  Stockfish at Maximum Strength")
    print(f"  Bot plays : {bot_plays.capitalize()}")
    print("  Commands  : undo | reset | top | quit")
    print("  Moves     : e2e4  or  e4  or  Nf3  or  O-O")
    print(f"{_DIVIDER}")

    bot_color = chess.WHITE if bot_plays == "white" else chess.BLACK

    while not bot.is_game_over:
        bot.display()
        print()

        is_bot_turn = (
            bot_plays == "both"
            or bot.board.turn == bot_color
        )

        if is_bot_turn:
            print(f"Bot ({bot.turn}) is thinking…")
            t0 = time.time()
            move = bot.best_move()
            elapsed = time.time() - t0
            san = bot.board.san(move)
            bot.board.push(move)
            print(f"  Played: {san}  ({elapsed:.1f}s)\n")
            continue

        # Human's turn
        while True:
            try:
                cmd = input(f"Your move ({bot.turn}): ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye!")
                return

            if not cmd:
                continue

            lower = cmd.lower()
            if lower == "quit":
                print("Goodbye!")
                return
            if lower == "reset":
                bot.reset()
                print("Board reset.\n")
                break
            if lower == "undo":
                bot.undo()  # undo bot's last reply
                bot.undo()  # undo your last move
                print("Last move pair undone.\n")
                break
            if lower == "top":
                print("  Top moves:")
                for san, ev in bot.top_moves(3):
                    print(f"    {san:<8} {ev}")
                continue

            try:
                # Accept both UCI and SAN
                try:
                    bot.push_uci(cmd)
                except ValueError:
                    bot.push_san(cmd)
                break
            except ValueError as exc:
                print(f"  Invalid: {exc}")

    if bot.is_game_over:
        bot.display()
        _print_outcome(bot.outcome)


def suggest_mode(bot: ChessBot, macos: MacOSChessInterface) -> None:
    """
    Watch macOS Chess and print top-3 moves for every new position.
    Requires macOS Chess to expose FEN via AppleScript.
    Press Ctrl-C to stop.
    """
    print(f"\n{_DIVIDER}")
    print("  Suggestion Mode  ·  monitoring macOS Chess")
    print("  Press Ctrl-C to stop.")
    print(f"{_DIVIDER}\n")

    macos.activate()
    last_fen: Optional[str] = None

    try:
        while True:
            fen = macos.get_fen()
            if fen and fen != last_fen:
                last_fen = fen
                try:
                    bot.apply_fen(fen)
                    print(f"\nTurn: {bot.turn}  |  Move #{bot.board.fullmove_number}")
                    print("  Top moves:")
                    for san, ev in bot.top_moves(3):
                        print(f"    {san:<8} {ev}")
                except Exception as exc:
                    print(f"  Error analysing position: {exc}")
            time.sleep(0.8)
    except KeyboardInterrupt:
        print("\nStopped.")


def auto_mode(
    bot: ChessBot,
    macos: MacOSChessInterface,
    play_as: str = "white",
) -> None:
    """
    Fully automated: bot reads board state from macOS Chess via AppleScript
    and plays moves back into the app automatically.

    Falls back to interactive terminal mode if FEN reading is unsupported.
    play_as: 'white' | 'black'
    """
    print(f"\n{_DIVIDER}")
    print(f"  Auto Mode  ·  Bot plays {play_as.capitalize()} vs macOS Chess")
    print(f"{_DIVIDER}\n")

    macos.activate()
    bot_color = chess.WHITE if play_as == "white" else chess.BLACK
    last_fen: Optional[str] = None

    try:
        while True:
            fen = macos.get_fen()

            if fen is None:
                print(
                    "macOS Chess does not expose its board position via AppleScript\n"
                    "on this version of macOS.\n\n"
                    "Falling back to interactive terminal mode.\n"
                    "Enter the opponent's moves manually when prompted.\n"
                )
                interactive_mode(bot, play_as)
                return

            if fen == last_fen:
                time.sleep(0.5)
                continue

            last_fen = fen

            try:
                bot.apply_fen(fen)
            except Exception as exc:
                print(f"FEN parse error: {exc}")
                continue

            if bot.is_game_over:
                bot.display()
                _print_outcome(bot.outcome)
                break

            if bot.board.turn != bot_color:
                # Opponent's turn — wait for their move
                time.sleep(0.4)
                continue

            print(f"Move {bot.board.fullmove_number} ({bot.turn}): thinking…")
            move = bot.best_move()
            san = bot.board.san(move)
            uci = move.uci()

            if macos.make_move(uci):
                print(f"  Played: {san}")
            else:
                print(f"  Auto-play failed for {san} ({uci}).")
                print(f"  Please play this move manually: {san}")

            time.sleep(0.4)

    except KeyboardInterrupt:
        print("\nStopped.")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="chess_bot.py",
        description=(
            "Chess bot that beats the macOS Chess app at maximum difficulty.\n"
            "Uses Stockfish at full strength (~3500 ELO) vs Sjeng (~2000 ELO)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
modes:
  interactive  Play in this terminal — enter moves, bot replies  (default)
  auto         Auto-play against macOS Chess via AppleScript
  suggest      Watch macOS Chess and print best moves for each position

examples:
  python chess_bot.py
  python chess_bot.py --color white
  python chess_bot.py --mode auto --color white --time 8
  python chess_bot.py --mode suggest
""",
    )
    p.add_argument(
        "--mode",
        choices=["interactive", "auto", "suggest"],
        default="interactive",
        help="Play mode (default: interactive)",
    )
    p.add_argument(
        "--color",
        choices=["white", "black", "both"],
        default="black",
        help="Color the bot plays in interactive/auto mode (default: black)",
    )
    p.add_argument(
        "--time",
        type=float,
        default=5.0,
        metavar="SECONDS",
        help="Thinking time per move (default: 5.0)",
    )
    p.add_argument(
        "--hash",
        type=int,
        default=512,
        metavar="MB",
        help="Stockfish hash table size in MB (default: 512)",
    )
    p.add_argument(
        "--threads",
        type=int,
        default=4,
        help="CPU threads for Stockfish (default: 4)",
    )
    p.add_argument(
        "--stockfish",
        metavar="PATH",
        default=None,
        help="Explicit path to the Stockfish binary",
    )
    return p


def main() -> None:
    args = _build_parser().parse_args()

    with ChessBot(
        stockfish_path=args.stockfish,
        think_time=args.time,
        hash_mb=args.hash,
        threads=args.threads,
    ) as bot:
        if args.mode == "interactive":
            interactive_mode(bot, args.color)
        elif args.mode == "suggest":
            suggest_mode(bot, MacOSChessInterface())
        elif args.mode == "auto":
            auto_mode(bot, MacOSChessInterface(), args.color)


if __name__ == "__main__":
    main()
