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


# ─────────────────────────────────────────────────────────────────────────────
# Game setup — open app, max difficulty, new game
# ─────────────────────────────────────────────────────────────────────────────

def _set_max_difficulty_via_menu() -> bool:
    """
    Game menu → Computer Level → click the last (highest) enabled item.
    Returns True on success.
    """
    result = _applescript(
        'tell application "System Events"\n'
        '    tell process "Chess"\n'
        '        try\n'
        '            tell menu bar 1\n'
        '                tell menu bar item "Game"\n'
        '                    tell menu "Game"\n'
        '                        tell menu item "Computer Level"\n'
        '                            tell menu "Computer Level"\n'
        '                                set lvls to every menu item whose enabled is true\n'
        '                                click last item of lvls\n'
        '                            end tell\n'
        '                        end tell\n'
        '                    end tell\n'
        '                end tell\n'
        '            end tell\n'
        '            return "ok"\n'
        '        on error errMsg\n'
        '            return errMsg\n'
        '        end try\n'
        '    end tell\n'
        'end tell'
    )
    return result == "ok"


def _set_max_difficulty_via_prefs() -> bool:
    """
    Open Preferences (⌘,), drag the Computer Level slider to its maximum,
    then close the window.  Returns True on success.
    """
    # Open Preferences
    _applescript(
        'tell application "System Events"\n'
        '    tell process "Chess"\n'
        '        keystroke "," using command down\n'
        '    end tell\n'
        'end tell'
    )
    time.sleep(0.9)

    result = _applescript(
        'tell application "System Events"\n'
        '    tell process "Chess"\n'
        '        try\n'
        '            tell window 1\n'
        '                set maxVal to maximum value of slider 1\n'
        '                set value of slider 1 to maxVal\n'
        '            end tell\n'
        '            return "ok"\n'
        '        on error errMsg\n'
        '            return errMsg\n'
        '        end try\n'
        '    end tell\n'
        'end tell'
    )
    time.sleep(0.3)

    # Close Preferences window
    _applescript(
        'tell application "System Events"\n'
        '    tell process "Chess"\n'
        '        keystroke "w" using command down\n'
        '    end tell\n'
        'end tell'
    )
    time.sleep(0.4)
    return result == "ok"


def _start_new_game_dialog(play_as: str) -> None:
    """
    Trigger New Game (⌘N), configure the sheet/dialog for the right
    game type, and confirm.

    play_as 'white' → Human vs Computer
    play_as 'black' → Computer vs Human
    """
    _applescript(
        'tell application "System Events"\n'
        '    tell process "Chess"\n'
        '        keystroke "n" using command down\n'
        '    end tell\n'
        'end tell'
    )
    time.sleep(1.2)

    # The new-game sheet has a popup button that controls game type.
    # Try to set it directly; if that fails, click through the popup manually.
    game_type = "Human vs Computer" if play_as == "white" else "Computer vs Human"

    set_result = _applescript(
        f'tell application "System Events"\n'
        f'    tell process "Chess"\n'
        f'        try\n'
        f'            tell window 1\n'
        f'                set value of pop up button 1 to "{game_type}"\n'
        f'            end tell\n'
        f'            return "ok"\n'
        f'        on error errMsg\n'
        f'            return errMsg\n'
        f'        end try\n'
        f'    end tell\n'
        f'end tell'
    )

    if set_result != "ok":
        # Fallback: click the popup to open it, then click the right menu item
        _applescript(
            f'tell application "System Events"\n'
            f'    tell process "Chess"\n'
            f'        try\n'
            f'            tell window 1\n'
            f'                click pop up button 1\n'
            f'                delay 0.4\n'
            f'                click menu item "{game_type}" of menu 1 of pop up button 1\n'
            f'            end tell\n'
            f'        end try\n'
            f'    end tell\n'
            f'end tell'
        )
        time.sleep(0.4)

    # Click the "Play" button (some macOS versions use "OK")
    _applescript(
        'tell application "System Events"\n'
        '    tell process "Chess"\n'
        '        try\n'
        '            tell window 1\n'
        '                click button "Play"\n'
        '            end tell\n'
        '        on error\n'
        '            try\n'
        '                tell window 1\n'
        '                    click button "OK"\n'
        '                end tell\n'
        '            end try\n'
        '        end try\n'
        '    end tell\n'
        'end tell'
    )
    time.sleep(1.0)


def setup_game(play_as: str = "white") -> None:
    """
    Full automated setup:
      1. Launch Chess.app
      2. Set computer difficulty to maximum
      3. Start a new game with the correct human/computer sides
    """
    print("Launching Chess.app…")
    _applescript('tell application "Chess" to activate')
    time.sleep(1.2)

    print("Setting difficulty to maximum…")
    if not _set_max_difficulty_via_menu():
        # Menu approach failed (e.g. no game is loaded yet) — try Preferences
        if _set_max_difficulty_via_prefs():
            print("  (used Preferences slider)")
        else:
            print("  Warning: could not set difficulty automatically.")
            print("  Please set Computer Level to maximum in Chess → Game menu.")
    time.sleep(0.3)

    print("Starting new game…")
    _start_new_game_dialog(play_as)
    print("Game started.\n")


def new_game() -> None:
    """Start a new game in Chess.app via Cmd+N (no setup)."""
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

# macOS Chess 2D square colours — wider ranges to survive theme/brightness
# differences.  Light squares: warm cream; dark squares: warm brown.
_LIGHT_LO = np.array([160, 130,  90], dtype=np.float32)
_LIGHT_HI = np.array([255, 248, 220], dtype=np.float32)
_DARK_LO  = np.array([ 90,  55,  25], dtype=np.float32)
_DARK_HI  = np.array([210, 165, 120], dtype=np.float32)


def _is_board_pixel(pixel: np.ndarray) -> bool:
    p = pixel[:3].astype(np.float32)
    # Require red > blue (warm tone) to reduce false positives from grey UI chrome
    if p[0] <= p[2]:
        return False
    light = np.all(p >= _LIGHT_LO) and np.all(p <= _LIGHT_HI)
    dark  = np.all(p >= _DARK_LO)  and np.all(p <= _DARK_HI)
    return light or dark


def _screen_scale() -> float:
    """
    Retina pixel scale factor.
    pyautogui.screenshot() returns physical pixels; window bounds from
    AppleScript are logical points.  On standard Retina this is 2.0.
    """
    img = pyautogui.screenshot(region=(0, 0, 10, 10))
    return img.width / 10.0


def detect_board(wx: int, wy: int, ww: int, wh: int) -> BoardGeometry:
    """
    Find the chessboard within the Chess.app window.

    Screenshots come back in *physical* pixels; window bounds are *logical*
    points.  We work entirely in physical space during detection, then divide
    by the scale factor before returning logical coords for clicking.
    """
    scale = _screen_scale()
    screenshot = pyautogui.screenshot(region=(wx, wy, ww, wh))
    img = np.array(screenshot)          # shape: (wh*scale, ww*scale, 3)
    ph, pw = img.shape[:2]              # physical pixel dimensions

    # ── Horizontal scan (find left/right board edges) ────────────────────────
    scan_y = ph // 2
    row = img[scan_y]
    board_cols = [x for x, px in enumerate(row) if _is_board_pixel(px)]

    if len(board_cols) >= int(8 * scale):   # found enough board pixels
        left_px  = min(board_cols)
        right_px = max(board_cols)
        width_px = right_px - left_px
    else:
        # Heuristic: board fills ~90 % of the shorter window dimension
        width_px = int(min(pw, ph) * 0.90)
        left_px  = (pw - width_px) // 2

    # ── Vertical scan (find top/bottom board edges) ──────────────────────────
    scan_x = left_px + width_px // 2
    col = img[:, scan_x]
    board_rows = [y for y, px in enumerate(col) if _is_board_pixel(px)]

    if len(board_rows) >= int(8 * scale):
        top_px    = min(board_rows)
        height_px = max(board_rows) - top_px
    else:
        height_px = width_px
        top_px    = (ph - height_px) // 2

    # Average width/height to get the square board size
    size_px = (width_px + height_px) // 2

    # ── Convert physical pixels → logical screen coords ──────────────────────
    # AppleScript and pyautogui.click() both use logical points; only
    # pyautogui.screenshot() returns physical pixels, hence the division.
    board_x    = wx + round(left_px  / scale)
    board_y    = wy + round(top_px   / scale)
    board_size = round(size_px / scale)

    return BoardGeometry(x=board_x, y=board_y, size=board_size)


def calibrate(geo: BoardGeometry) -> None:
    """
    Slowly move the mouse around the four corners of the detected board so
    the user can confirm the detection is correct before the game begins.
    """
    corners = [
        ("a1", geo.to_pixel(chess.A1)),
        ("a8", geo.to_pixel(chess.A8)),
        ("h8", geo.to_pixel(chess.H8)),
        ("h1", geo.to_pixel(chess.H1)),
        ("a1", geo.to_pixel(chess.A1)),   # close the loop
    ]
    print("Tracing board corners to verify detection (a1→a8→h8→h1)…")
    for label, (x, y) in corners:
        pyautogui.moveTo(x, y, duration=0.5)
        time.sleep(0.2)
    print("  Corners traced.  If the mouse outlined the board correctly, "
          "detection is good.\n")


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

    Works directly in physical pixel space (image dimensions) so results are
    correct regardless of Retina scale factor.
    """
    h, w = before.shape[:2]    # physical pixel dimensions of the captured board
    sq_h = h / 8
    sq_w = w / 8
    result: list[chess.Square] = []

    for rank in range(8):
        for file in range(8):
            r0 = int(rank       * sq_h);  r1 = int((rank + 1) * sq_h)
            c0 = int(file       * sq_w);  c1 = int((file + 1) * sq_w)
            diff = np.abs(
                before[r0:r1, c0:c1].astype(np.float32) -
                after[r0:r1,  c0:c1].astype(np.float32)
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
    """Bring Chess.app to front, then click source square → destination square."""
    # Chess must own the mouse events or the clicks are silently dropped
    _applescript('tell application "Chess" to activate')
    time.sleep(0.25)

    sx, sy = geo.to_pixel(move.from_square)
    dx, dy = geo.to_pixel(move.to_square)

    pyautogui.moveTo(sx, sy, duration=0.20)
    pyautogui.click()
    time.sleep(0.40)
    pyautogui.moveTo(dx, dy, duration=0.20)
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
    setup_game(play_as)

    # Let the board fully render after new-game setup
    time.sleep(1.5)

    wx, wy, ww, wh = get_window_bounds()
    geo = detect_board(wx, wy, ww, wh)
    geo.flipped = play_as == "black"

    print(f"Board detected  : origin=({geo.x}, {geo.y})  size={geo.size}px  "
          f"sq={geo.sq_px:.1f}px")
    print(f"Bot plays       : {play_as.capitalize()}")
    print(f"Think time      : {think_time}s per move")
    print("Fail-safe       : move mouse to top-left corner to abort\n")

    # Visually trace the board corners — user can confirm it's correct
    calibrate(geo)

    bot_color = chess.WHITE if play_as == "white" else chess.BLACK

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
