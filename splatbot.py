from utils.actions import Actions
from utils.hex_grid import HexUtils, HexDirection
from utils.splatbot_data_types import GameState


class Bot:
    """
    Strategy:
    - Every turn, score all 6 directions by summing tile values up to 6 hexes
      ahead (unclaimed=2, opponent=3, ours=0), weighted for proximity.
    - Turn toward the best direction, then move.
    - Splat (paints all 6 neighbors) when off cooldown and the neighbors are
      worth at least 6 value (3 unclaimed or 2 opponent tiles, etc.).
    - Dash when already facing the best direction but the next two tiles are
      already ours — skip ahead to fresh territory.
    - Skip only when stunned.
    """

    # ── Scoring helpers ───────────────────────────────────────────────────────

    def _tile_value(self, tile, my_pid: int) -> int:
        """How desirable is it to paint this tile?"""
        if tile.controller is None:
            return 2  # Unclaimed
        if not tile.is_controlled_by(my_pid):
            return 3  # Steal from opponent — highest priority
        return 0      # Already ours

    def _direction_score(
        self, hex_utils: HexUtils, pos, direction, my_pid: int, depth: int = 6
    ) -> int:
        """Sum tile values along `direction` for up to `depth` hexes.
        Closer tiles are weighted more heavily."""
        score = 0
        current = pos
        for i in range(depth):
            nxt = hex_utils.hex_neighbor(current, direction)
            tile = hex_utils.hex_at(nxt)
            if tile is None:
                break
            score += self._tile_value(tile, my_pid) * (depth - i)
            current = nxt
        return score

    def _best_direction(self, hex_utils: HexUtils, pos, my_pid: int):
        """Return (HexDirection, score) for the most promising direction."""
        best_dir, best_score = None, -1
        for d in HexDirection:
            s = self._direction_score(hex_utils, pos, d, my_pid)
            if s > best_score:
                best_score, best_dir = s, d
        return best_dir, best_score

    def _turn_toward(self, current: HexDirection, target: HexDirection):
        """Shortest-path turn action to face `target`, or None if already there."""
        left_steps = (int(target) - int(current)) % 6
        right_steps = (int(current) - int(target)) % 6
        if left_steps == 0:
            return None
        if left_steps <= right_steps:
            return Actions.turn_left(left_steps)
        return Actions.turn_right(right_steps)

    # ── Main decision ─────────────────────────────────────────────────────────

    def decide(self, game_state: GameState):
        player = game_state.me

        # Skip is the only legal action while stunned
        if player.stun > 0:
            return Actions.skip()

        hex_utils = HexUtils(game_state)
        pos = player.position
        my_pid = player.pid

        # ── Splat ────────────────────────────────────────────────────────────
        # Paint all 6 neighbors instantly — great at intersections with unclaimed
        # or opponent tiles. Cost: 3-turn stun + 10-turn cooldown.
        if player.splat_cooldown == 0:
            neighbors = hex_utils.in_grid_neighbors(pos)
            splat_value = sum(self._tile_value(t, my_pid) for t in neighbors)
            if splat_value >= 6:  # e.g. ≥3 unclaimed or ≥2 opponent tiles nearby
                return Actions.splat()

        # ── Pick the best direction ──────────────────────────────────────────
        best_dir, _ = self._best_direction(hex_utils, pos, my_pid)

        # ── Dash ─────────────────────────────────────────────────────────────
        # Walk ahead tile-by-tile to find the first unowned tile.
        # Dash there only if at least one owned tile would be skipped (dist ≥ 2)
        # — otherwise just move so we don't skip tiles we could paint.
        if player.dash_cooldown == 0 and best_dir == player.facing:
            look = pos
            dash_distance = None
            for dist in range(1, 7):
                look = hex_utils.hex_neighbor(look, player.facing)
                tile = hex_utils.hex_at(look)
                if tile is None:
                    break  # Hit map edge before finding a target
                if not tile.is_controlled_by(my_pid):
                    # First unowned tile found — only worth dashing if we skip ≥1 owned tile
                    if dist >= 2:
                        dash_distance = dist
                    break  # Stop regardless; don't skip tiles we could paint further ahead
            if dash_distance is not None:
                return Actions.dash(dash_distance)

        # ── Turn toward the best direction ───────────────────────────────────
        if best_dir is not None:
            turn = self._turn_toward(player.facing, best_dir)
            if turn is not None:
                return turn

        # ── Move (or reverse at map edge) ────────────────────────────────────
        ahead = hex_utils.hex_neighbor(pos, player.facing)
        if ahead not in game_state.grid:
            return Actions.turn_180()

        return Actions.move()
