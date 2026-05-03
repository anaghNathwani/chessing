"""
Physical GUI controller for macOS Chess.app.

Locates the chessboard on screen, watches for the opponent's move via
screenshot diffs, and physically clicks pieces to make the bot's moves.

Requires:
    pip install pyautogui numpy pillow
    System Settings → Privacy & Security → Accessibility → enable Terminal
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional

import chess
import numpy as np
import pyautogui

# Smooth out pyautogui; keep it fast but not jarring
pyautogui.PAUSE = 0.05
pyautogui.FAILSAFE = True   # move mouse to top-left corner to abort at any time


# ─────────────────────────────────────────────────────────────────────────────
# Board geometry
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BoardGeometry:
    """Screen coordinates of the chessboard and helpers to map squares ↔ pixels."""

    x: int          # screen x of board top-left
    y: int          # screen y of board top-left
    size: int       # side length in pixels (board is always square)
    flipped: bool = False   # True when bot plays as Black

    @property
    def sq_px(self) -> float:
        return self.size / 8

    def to_pixel(self, square: chess.Square) -> tuple[int, int]:
        f = chess.square_file(square)
        r = chess.square_rank(square)
        if self.flipped:
            f, r = 7 - f, 7 - r
        px = int(self.x + (f + 0.5) * self.sq_px)
        py = int(self.y + (7 - r + 0.5) * self.sq_px)
        return px, py

    def from_pixel(self, px: int, py: int) -> Optional[chess.Square]:
        f = int((px - self.x) / self.sq_px)
        r = 7 - int((py - self.y) / self.sq_px)
        if self.flipped:
            f, r = 7 - f, 7 - r
        if 0 <= f <= 7 and 0 <= r <= 7:
            return chess.square(f, r)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# macOS Chess window helpers
# ─────────────────────────────────────────────────────────────────────────────

def _applescript(script: str) -> str:
    r = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=10,
    )
    return r.stdout.strip()


def activate_chess() -> None:
    _applescript('tell application "Chess" to activate')
    time.sleep(0.8)


def new_game() -> None:
    """Start a new game in Chess.app via Cmd+N."""
    activate_chess()
    _applescript(
        'tell application "System Events"\n'
        '    tell process "Chess"\n'
        '        keystroke "n" using command down\n'
        '    end tell\n'
        'end tell'
    )
    time.sleep(1.2)


def get_window_bounds() -> tuple[int, int, int, int]:
    """Return (x, y, width, height) of the Chess.app window."""
    raw = _applescript(
        'tell application "System Events"\n'
        '    tell process "Chess"\n'
        '        set w to first window\n'
        '        set pos to position of w\n'
        '        set sz to size of w\n'
        '        return ((item 1 of pos) as string) & "," '
        '             & ((item 2 of pos) as string) & "," '
        '             & ((item 1 of sz) as string) & "," '
        '             & ((item 2 of sz) as string)\n'
        '    end tell\n'
        'end tell'
    )
    try:
        return tuple(map(int, raw.split(",")))  # type: ignore[return-value]
    except ValueError:
        sys.exit(
            f"\nCannot read Chess.app window bounds.\n"
            f"AppleScript returned: {raw!r}\n\n"
            "Make sure:\n"
            "  1. Chess.app is open\n"
            "  2. Terminal has Accessibility permission:\n"
            "     System Settings → Privacy & Security → Accessibility\n"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Board detection
# ─────────────────────────────────────────────────────────────────────────────

# macOS Chess 2D square colours (approximate)
_LIGHT_LO = np.array([190, 165, 130], dtype=np.float32)
_LIGHT_HI = np.array([255, 235, 210], dtype=np.float32)
_DARK_LO  = np.array([120,  85,  50], dtype=np.float32)
_DARK_HI  = np.array([200, 160, 120], dtype=np.float32)


def _is_board_pixel(pixel: np.ndarray) -> bool:
    p = pixel[:3].astype(np.float32)
    light = np.all(p >= _LIGHT_LO) and np.all(p <= _LIGHT_HI)
    dark  = np.all(p >= _DARK_LO)  and np.all(p <= _DARK_HI)
    return light or dark


def detect_board(wx: int, wy: int, ww: int, wh: int) -> BoardGeometry:
    """
    Find the chessboard within the Chess.app window by scanning for the
    characteristic light/dark square colour pattern.
    Falls back to a window-based heuristic if colour detection fails.
    """
    img = np.array(pyautogui.screenshot(region=(wx, wy, ww, wh)))

    # Scan the horizontal centre of the window for board-coloured pixels
    scan_y = wh // 2
    row = img[scan_y]
    board_cols = [x for x, px in enumerate(row) if _is_board_pixel(px)]

    if len(board_cols) >= 8:
        left  = min(board_cols)
        right = max(board_cols)
        width = right - left
    else:
        # Heuristic fallback — board fills ~90 % of the window width
        width = int(min(ww, wh) * 0.90)
        left  = (ww - width) // 2

    # Scan vertically at the horizontal centre of the detected board
    scan_x = left + width // 2
    col = img[:, scan_x]
    board_rows = [y for y, px in enumerate(col) if _is_board_pixel(px)]

    if len(board_rows) >= 8:
        top    = min(board_rows)
        height = max(board_rows) - top
    else:
        height = width
        top    = (wh - height) // 2

    size = (width + height) // 2   # average in case of slight asymmetry
    return BoardGeometry(x=wx + left, y=wy + top, size=size)


# ─────────────────────────────────────────────────────────────────────────────
# Screenshot helpers
# ─────────────────────────────────────────────────────────────────────────────

def grab_board(geo: BoardGeometry) -> np.ndarray:
    """Capture the board area as a (size × size × 3) uint8 array."""
    img = pyautogui.screenshot(region=(geo.x, geo.y, geo.size, geo.size))
    return np.array(img)


def changed_squares(
    before: np.ndarray,
    after: np.ndarray,
    geo: BoardGeometry,
    threshold: float = 18.0,
) -> list[chess.Square]:
    """
    Return the chess squares where the average pixel value changed significantly
    between two board screenshots.  These are the squares involved in a move.
    """
    sq = int(geo.sq_px)
    result: list[chess.Square] = []

    for rank in range(8):
        for file in range(8):
            r0, r1 = rank * sq, (rank + 1) * sq
            c0, c1 = file * sq, (file + 1) * sq
            diff = np.abs(
                before[r0:r1, c0:c1].astype(np.float32) -
                after[r0:r1, c0:c1].astype(np.float32)
            ).mean()
            if diff > threshold:
                if not geo.flipped:
                    result.append(chess.square(file, 7 - rank))
                else:
                    result.append(chess.square(7 - file, rank))

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Move inference
# ─────────────────────────────────────────────────────────────────────────────

def infer_move(
    squares: list[chess.Square],
    board: chess.Board,
) -> Optional[chess.Move]:
    """
    Given the set of changed squares and the board state BEFORE the move,
    find which legal move best explains the observed changes.

    Handles normal moves, castling (king + rook both move),
    en passant (three squares change), and promotions.
    """
    sq_set = set(squares)
    legal  = list(board.legal_moves)

    for move in legal:
        involved = {move.from_square, move.to_square}

        # Castling: rook also moves
        if board.is_castling(move):
            if move.to_square == chess.G1:
                involved |= {chess.H1, chess.F1}
            elif move.to_square == chess.C1:
                involved |= {chess.A1, chess.D1}
            elif move.to_square == chess.G8:
                involved |= {chess.H8, chess.F8}
            elif move.to_square == chess.C8:
                involved |= {chess.A8, chess.D8}

        # En passant: captured pawn square also changes
        if board.is_en_passant(move):
            ep = chess.square(
                chess.square_file(move.to_square),
                chess.square_rank(move.from_square),
            )
            involved.add(ep)

        # Accept if observed changes are a subset/superset of expected squares
        # (animations may briefly mark extra squares)
        if involved <= sq_set or sq_set <= involved:
            return move

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Move execution
# ─────────────────────────────────────────────────────────────────────────────

def click_move(move: chess.Move, geo: BoardGeometry) -> None:
    """Click the source square, then the destination square."""
    sx, sy = geo.to_pixel(move.from_square)
    dx, dy = geo.to_pixel(move.to_square)

    pyautogui.moveTo(sx, sy, duration=0.12)
    pyautogui.click()
    time.sleep(0.30)
    pyautogui.moveTo(dx, dy, duration=0.12)
    pyautogui.click()


def handle_promotion(geo: BoardGeometry, piece: int = chess.QUEEN) -> None:
    """
    Click the correct piece in macOS Chess's promotion picker.
    The picker appears at the promotion rank; pieces are ordered
    Queen → Rook → Bishop → Knight from left (or right when flipped).
    """
    time.sleep(0.65)
    order = [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]
    idx = order.index(piece) if piece in order else 0

    sq_px = int(geo.sq_px)
    # The picker row appears roughly at the top of the board for white promotions
    picker_y = geo.y + sq_px // 2
    picker_x = geo.x + idx * sq_px + sq_px // 2

    pyautogui.moveTo(picker_x, picker_y, duration=0.1)
    pyautogui.click()


# ─────────────────────────────────────────────────────────────────────────────
# Opponent move detection
# ─────────────────────────────────────────────────────────────────────────────

def wait_for_opponent(
    geo: BoardGeometry,
    board: chess.Board,
    timeout: float = 120.0,
    poll: float = 0.4,
) -> Optional[chess.Move]:
    """
    Poll screenshots until the board changes, then return the inferred move.
    Returns None if timeout expires without a valid move being detected.
    """
    baseline = grab_board(geo)
    deadline = time.time() + timeout
    stable_count = 0   # require N consistent detections to filter animation frames

    pending_move: Optional[chess.Move] = None

    while time.time() < deadline:
        time.sleep(poll)
        current   = grab_board(geo)
        squares   = changed_squares(baseline, current, geo)

        if len(squares) >= 2:
            move = infer_move(squares, board)
            if move is not None:
                if move == pending_move:
                    stable_count += 1
                else:
                    pending_move  = move
                    stable_count  = 1

                # Confirm after 2 consecutive identical readings
                if stable_count >= 2:
                    return move
        else:
            pending_move = None
            stable_count = 0

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Main game loop
# ─────────────────────────────────────────────────────────────────────────────

def play(bot: object, play_as: str = "white", think_time: float = 5.0) -> None:
    """
    Physically play a full game against macOS Chess.

    bot       : a ChessBot instance (from chess_bot.py)
    play_as   : 'white' or 'black'
    think_time: seconds Stockfish gets per move
    """
    print("\nActivating Chess.app…")
    activate_chess()

    wx, wy, ww, wh = get_window_bounds()
    geo = detect_board(wx, wy, ww, wh)
    geo.flipped = play_as == "black"

    print(f"Board detected  : origin=({geo.x}, {geo.y})  size={geo.size}px")
    print(f"Bot plays       : {play_as.capitalize()}")
    print(f"Think time      : {think_time}s per move")
    print("Move mouse to top-left corner at any time to abort (pyautogui fail-safe).\n")

    bot_color = chess.WHITE if play_as == "white" else chess.BLACK

    # Give the user a moment to ensure the game is ready
    time.sleep(1.5)

    while not bot.is_game_over:  # type: ignore[attr-defined]
        current_board: chess.Board = bot.board  # type: ignore[attr-defined]

        if current_board.turn == bot_color:
            move_num = current_board.fullmove_number
            print(f"[{move_num}] Thinking…", flush=True)

            move = bot.best_move(think_time)  # type: ignore[attr-defined]
            san  = current_board.san(move)

            click_move(move, geo)

            if move.promotion:
                handle_promotion(geo, move.promotion)

            current_board.push(move)
            print(f"     Bot played : {san}")
            time.sleep(0.5)

        else:
            move_num = current_board.fullmove_number
            print(f"[{move_num}] Waiting for opponent…", flush=True)

            opponent_move = wait_for_opponent(geo, current_board, timeout=120.0)

            if opponent_move is None:
                print("Timed out waiting for opponent. Stopping.")
                break

            san = current_board.san(opponent_move)
            current_board.push(opponent_move)
            print(f"     Opponent   : {san}")

    # Game over
    outcome = bot.outcome  # type: ignore[attr-defined]
    if outcome:
        if outcome.winner is None:
            print("\nResult: Draw")
        elif outcome.winner == chess.WHITE:
            print("\nResult: White wins")
        else:
            print("\nResult: Black wins")
    else:
        print("\nGame ended.")
