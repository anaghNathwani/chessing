"""
Physical GUI controller for macOS Chess.app.

Locates the chessboard on screen, watches for the opponent's move via
screenshot diffs, and physically clicks pieces to make the bot's moves.

Requires:
    pip install pyautogui numpy pillow
    python3 -m pip install google-generativeai   # for Gemini board-state verification
    System Settings → Privacy & Security → Accessibility → enable Terminal
"""

from __future__ import annotations

import subprocess
import sys
import time
import json as _json
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


def detect_board(
    wx: int, wy: int, ww: int, wh: int,
    gemini: Optional["GeminiVision"] = None,
) -> BoardGeometry:
    """
    Find the chessboard within the Chess.app window.

    When *gemini* is provided it is asked first — it can locate the board in
    any theme (2D, 3D, custom colours) without any hardcoded assumptions.
    Falls back to colour-scanning when Gemini is unavailable or fails.

    Screenshots come back in *physical* pixels; window bounds are *logical*
    points.  All detected pixel offsets are divided by the scale factor before
    being stored so that to_pixel() returns correct logical coords for clicking.
    """
    scale = _screen_scale()
    screenshot = pyautogui.screenshot(region=(wx, wy, ww, wh))
    img = np.array(screenshot)          # shape: (wh*scale, ww*scale, 3)
    ph, pw = img.shape[:2]

    # ── Strategy 1: ask Gemini (works with any board style) ──────────────────
    if gemini is not None:
        rect = gemini.find_board(img)
        if rect:
            x_px, y_px, w_px, h_px = rect
            size_px = (w_px + h_px) // 2
            return BoardGeometry(
                x    = wx + round(x_px   / scale),
                y    = wy + round(y_px   / scale),
                size = round(size_px / scale),
            )
        print("  [Gemini] Board detection failed — falling back to colour scan.")

    # ── Strategy 2: colour-based scan ────────────────────────────────────────
    scan_y = ph // 2
    row = img[scan_y]
    board_cols = [x for x, px in enumerate(row) if _is_board_pixel(px)]

    if len(board_cols) >= int(8 * scale):
        left_px  = min(board_cols)
        right_px = max(board_cols)
        width_px = right_px - left_px
    else:
        width_px = int(min(pw, ph) * 0.90)
        left_px  = (pw - width_px) // 2

    scan_x = left_px + width_px // 2
    col = img[:, scan_x]
    board_rows = [y for y, px in enumerate(col) if _is_board_pixel(px)]

    if len(board_rows) >= int(8 * scale):
        top_px    = min(board_rows)
        height_px = max(board_rows) - top_px
    else:
        height_px = width_px
        top_px    = (ph - height_px) // 2

    size_px = (width_px + height_px) // 2
    return BoardGeometry(
        x    = wx + round(left_px  / scale),
        y    = wy + round(top_px   / scale),
        size = round(size_px / scale),
    )


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


def _move_from_board_diff(
    before: chess.Board,
    after_fen: str,
) -> Optional[chess.Move]:
    """
    Walk every legal move from *before* and return the one whose resulting
    board-FEN matches *after_fen* (piece-placement field only).
    Returns None when no legal move explains the observed position.
    """
    target = after_fen.split()[0] if " " in after_fen else after_fen
    for move in before.legal_moves:
        test = before.copy()
        test.push(move)
        if test.board_fen() == target:
            return move
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Gemini Vision — primary sensor for all screen-reading tasks
# ─────────────────────────────────────────────────────────────────────────────

class GeminiVision:
    """
    Uses Gemini Vision as the single source of truth for everything visual:

      • find_board()           – locates the 8×8 grid anywhere on screen,
                                 replacing the fragile colour-scanning approach
      • read_state()           – returns FEN + game-over flag in one call,
                                 works with any board theme (2D, 3D, custom)
      • find_promotion_click() – finds exactly where to click in the promotion
                                 picker, replacing hardcoded pixel offsets
      • get_move()             – convenience wrapper used by wait_for_opponent

    All responses are structured JSON at temperature=0 so parsing is reliable.
    Screenshots are taken automatically — no user interaction required.
    """

    _SYSTEM = (
        "You are an expert chess vision system embedded in a chess bot. "
        "You analyse screenshots of macOS Chess.app and return precise JSON. "
        "You have deep knowledge of chess piece appearances in both 2D and 3D "
        "board styles. Every pixel-coordinate or FEN error costs the game, "
        "so be exact. Never add explanation — return only valid JSON."
    )

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        try:
            import google.generativeai as genai  # type: ignore[import]
        except ImportError:
            sys.exit(
                "\nGemini Vision requires the Google AI SDK.\n"
                "Install it into the same Python that runs this script:\n"
                "  python3 -m pip install google-generativeai\n"
            )
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(
            model_name=model,
            system_instruction=self._SYSTEM,
        )

    # ── Internal helper ───────────────────────────────────────────────────────

    def _ask(self, img: np.ndarray, prompt: str) -> Optional[dict]:
        """
        Send *img* to Gemini with *prompt* and return the parsed JSON dict.
        Uses response_mime_type='application/json' and temperature=0 so the
        output is deterministic and always well-formed JSON.
        """
        from PIL import Image  # type: ignore[import]
        pil = Image.fromarray(img)
        try:
            resp = self._model.generate_content(
                [prompt, pil],
                generation_config={
                    "response_mime_type": "application/json",
                    "temperature": 0.0,
                },
            )
            return _json.loads(resp.text)
        except Exception as exc:
            print(f"  [Gemini] {exc}")
            return None

    # ── Public API ────────────────────────────────────────────────────────────

    def find_board(self, window_img: np.ndarray) -> Optional[tuple[int, int, int, int]]:
        """
        Locate the 8×8 chessboard in a full window screenshot.
        Returns (x, y, width, height) in image pixels, or None on failure.

        This replaces colour-based board detection and works with any board
        theme — the bot no longer needs hardcoded colour ranges.
        """
        data = self._ask(
            window_img,
            "Find the 8×8 chessboard grid in this macOS Chess.app screenshot. "
            "Exclude the window title bar, toolbar, and any status areas. "
            'Return JSON: {"x": left_pixel, "y": top_pixel, '
            '"w": width_pixels, "h": height_pixels}',
        )
        if data and all(k in data for k in ("x", "y", "w", "h")):
            return int(data["x"]), int(data["y"]), int(data["w"]), int(data["h"])
        return None

    def read_state(
        self,
        board_img: np.ndarray,
        flipped: bool = False,
    ) -> Optional[dict]:
        """
        Read the complete game state from a board screenshot in a single call.

        Returns a dict with keys:
          "fen"       – piece-placement field (e.g. 'rnbqkbnr/pppppppp/8/8/…')
          "game_over" – true when the game has ended
          "result"    – null | "1-0" | "0-1" | "1/2-1/2"

        flipped=True means Black's pieces are at the bottom of the image.
        Works with 2D and 3D board styles, any colour theme.
        """
        side = "Black" if flipped else "White"
        data = self._ask(
            board_img,
            f"{side} pieces are at the bottom of the image. "
            "Analyse this chess position carefully — every piece matters. "
            "Return JSON with these exact keys:\n"
            '{"fen": "<piece_placement_only>", "game_over": false, "result": null}\n'
            "FEN rules: uppercase=white (K Q R B N P), lowercase=black (k q r b n p), "
            "digits=consecutive empty squares, ranks 8→1 separated by /. "
            'Set game_over=true and result to "1-0", "0-1", or "1/2-1/2" '
            "only when the game has actually ended.",
        )
        if (
            data
            and isinstance(data.get("fen"), str)
            and data["fen"].count("/") == 7
        ):
            return data
        return None

    def find_promotion_click(
        self,
        board_img: np.ndarray,
        piece: str = "queen",
    ) -> Optional[tuple[int, int]]:
        """
        After a pawn reaches the last rank, a piece-picker appears.
        Returns the (x, y) pixel within *board_img* to click for *piece*,
        or None if the picker isn't visible.

        This replaces hardcoded offsets that broke on non-default window sizes.
        """
        data = self._ask(
            board_img,
            f"A pawn-promotion piece picker is visible on this chess board. "
            f"Find the centre of the {piece} option and return its pixel "
            f'coordinates within this image. JSON: {{"x": pixel_x, "y": pixel_y}} '
            f"If no promotion picker is visible return null.",
        )
        if data and "x" in data and "y" in data:
            return int(data["x"]), int(data["y"])
        return None

    def get_move(
        self,
        board_img: np.ndarray,
        board_before: chess.Board,
        flipped: bool = False,
    ) -> Optional[chess.Move]:
        """
        Read the current board state from *board_img* and return the legal move
        that transitions *board_before* to the observed position.
        Returns None when Gemini can't read the board or no legal move matches.
        """
        state = self.read_state(board_img, flipped=flipped)
        if state is None:
            return None
        move = _move_from_board_diff(board_before, state["fen"])
        if move is None:
            print(f"  [Gemini] FEN '{state['fen']}' matches no legal move — "
                  "will retry next poll.")
        return move


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


def handle_promotion(
    geo: BoardGeometry,
    piece: int = chess.QUEEN,
    gemini: Optional["GeminiVision"] = None,
) -> None:
    """
    Click the correct piece in macOS Chess's promotion picker.

    When *gemini* is provided it takes a screenshot of the board and asks
    Gemini exactly where the promotion picker is — no hardcoded offsets.
    Falls back to a positional heuristic when Gemini is unavailable.
    """
    time.sleep(0.65)   # wait for the picker to fully appear

    piece_names = {
        chess.QUEEN: "queen", chess.ROOK: "rook",
        chess.BISHOP: "bishop", chess.KNIGHT: "knight",
    }
    piece_name = piece_names.get(piece, "queen")

    # ── Strategy 1: ask Gemini where to click ────────────────────────────────
    if gemini is not None:
        img = grab_board(geo)
        click_pos = gemini.find_promotion_click(img, piece_name)
        if click_pos:
            scale = _screen_scale()
            px = geo.x + round(click_pos[0] / scale)
            py = geo.y + round(click_pos[1] / scale)
            pyautogui.moveTo(px, py, duration=0.15)
            pyautogui.click()
            return

    # ── Strategy 2: positional heuristic ─────────────────────────────────────
    order = [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]
    idx   = order.index(piece) if piece in order else 0
    sq_px = int(geo.sq_px)
    pyautogui.moveTo(
        geo.x + idx * sq_px + sq_px // 2,
        geo.y + sq_px // 2,
        duration=0.15,
    )
    pyautogui.click()


# ─────────────────────────────────────────────────────────────────────────────
# Opponent move detection
# ─────────────────────────────────────────────────────────────────────────────

def wait_for_opponent(
    geo: BoardGeometry,
    board: chess.Board,
    timeout: float = 120.0,
    poll: float = 0.4,
    gemini: Optional[GeminiVision] = None,
) -> Optional[chess.Move]:
    """
    Poll screenshots until the board changes, then return the inferred move.

    When *gemini* is provided the workflow is:
      1. Screenshot diff detects *when* something changed (fast, no API call).
      2. Gemini Vision reads *what* the new position is (accurate, robust).
      3. The move is inferred by comparing before/after board states.
    Without Gemini the diff-based heuristic is used as before.

    Returns None if the timeout expires.
    """
    baseline     = grab_board(geo)
    deadline     = time.time() + timeout
    stable_count = 0
    pending_move: Optional[chess.Move] = None

    while time.time() < deadline:
        time.sleep(poll)
        current = grab_board(geo)
        squares = changed_squares(baseline, current, geo)

        if len(squares) < 2:
            pending_move = None
            stable_count = 0
            continue

        # Board has changed — try to identify the move
        if gemini is not None:
            # Let the animation settle for one extra poll before asking Gemini
            time.sleep(poll)
            current = grab_board(geo)
            move = gemini.get_move(current, board, flipped=geo.flipped)
            if move is not None:
                if move == pending_move:
                    stable_count += 1
                else:
                    pending_move = move
                    stable_count = 1
                if stable_count >= 2:
                    return move
            # Gemini failed this frame — keep polling
        else:
            # Diff-only fallback
            move = infer_move(squares, board)
            if move is not None:
                if move == pending_move:
                    stable_count += 1
                else:
                    pending_move = move
                    stable_count = 1
                if stable_count >= 2:
                    return move

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Main game loop
# ─────────────────────────────────────────────────────────────────────────────

def play(
    bot: object,
    play_as: str = "white",
    think_time: float = 5.0,
    gemini_key: Optional[str] = None,
    gemini_model: str = "gemini-2.0-flash",
) -> None:
    """
    Physically play a full game against macOS Chess.

    bot         : a ChessBot instance (from chess_bot.py)
    play_as     : 'white' or 'black'
    think_time  : seconds Stockfish gets per move
    gemini_key  : Gemini API key; if provided, Gemini Vision reads the board
                  after every opponent move for accurate state tracking
    gemini_model: which Gemini model to use (default: gemini-2.0-flash)
    """
    setup_game(play_as)

    # Let the board fully render after new-game setup
    time.sleep(1.5)

    # Initialise Gemini Vision if a key was supplied
    gemini: Optional[GeminiVision] = None
    if gemini_key:
        gemini = GeminiVision(api_key=gemini_key, model=gemini_model)
        print("Gemini Vision  : enabled (board find + state read + promotion)")
    else:
        print("Gemini Vision  : disabled (pass --gemini-key to enable)")

    wx, wy, ww, wh = get_window_bounds()
    # Gemini locates the board; colour-scan is the fallback
    geo = detect_board(wx, wy, ww, wh, gemini=gemini)
    geo.flipped = play_as == "black"

    print(f"Board detected  : origin=({geo.x}, {geo.y})  size={geo.size}px  "
          f"sq={geo.sq_px:.1f}px")
    print(f"Bot plays       : {play_as.capitalize()}")
    print(f"Think time      : {think_time}s per move")
    print("Fail-safe       : move mouse to top-left corner to abort\n")

    calibrate(geo)

    bot_color = chess.WHITE if play_as == "white" else chess.BLACK

    while not bot.is_game_over:  # type: ignore[attr-defined]
        current_board: chess.Board = bot.board  # type: ignore[attr-defined]

        # ── Check for game over via Gemini (catches checkmate dialogs etc.) ──
        if gemini is not None:
            state = gemini.read_state(grab_board(geo), flipped=geo.flipped)
            if state and state.get("game_over"):
                result = state.get("result") or "unknown"
                print(f"\nGemini detected game over — result: {result}")
                break

        if current_board.turn == bot_color:
            move_num = current_board.fullmove_number
            print(f"[{move_num}] Thinking…", flush=True)

            move = bot.best_move(think_time)  # type: ignore[attr-defined]
            san  = current_board.san(move)

            click_move(move, geo)

            if move.promotion:
                handle_promotion(geo, move.promotion, gemini=gemini)

            current_board.push(move)
            print(f"     Bot played : {san}")
            time.sleep(0.5)

        else:
            move_num = current_board.fullmove_number
            print(f"[{move_num}] Waiting for opponent…", flush=True)

            opponent_move = wait_for_opponent(
                geo, current_board, timeout=120.0, gemini=gemini
            )

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
