from collections import deque

from utils.actions import Actions
from utils.hex_grid import HexDirection
from utils.splatbot_data_types import GameState

# Axial (dq, dr) offsets in HexDirection enum order: E NE NW W SW SE
_OFFSETS = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]
_TO_DIR = {off: HexDirection(i) for i, off in enumerate(_OFFSETS)}


class Bot:
    """
    Offensive bot — maximize opponent stun, minimize self stun.

    Weapons:
    - shoot_paintball (any LOS range): stuns opponent 7 turns, cooldown 20
    - splat (adjacent only):           stuns opponent 3 turns, cooldown 10, paints 6 tiles

    Priority each tick:
    1. Skip if stunned.
    2. Opponent in LOS + our paintball ready → turn to face + shoot.
    3. Opponent adjacent + our splat ready   → splat.
    4. Opponent can shoot us (in their LOS, their paintball ready, ours not) → dodge.
    5. Opponent in LOS but paintball cooling → advance (close range for next shot/splat).
    6. No LOS → BFS toward opponent.
    7. Move forward; turn_180 at map edge.
    """

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _shooting_dir(self, pos, target, gd):
        """HexDirection in which target lies on a clear ray, or None."""
        for d, (dq, dr) in enumerate(_OFFSETS):
            cur = pos
            while True:
                nk = (cur[0] + dq, cur[1] + dr)
                if nk not in gd:
                    break
                if nk == target:
                    return HexDirection(d)
                cur = nk
        return None

    def _bfs_dir(self, pos, target, gd):
        """First HexDirection step toward target via BFS, or None if already there."""
        if pos == target:
            return None
        visited = {pos}
        queue = deque()
        for d, (dq, dr) in enumerate(_OFFSETS):
            nk = (pos[0] + dq, pos[1] + dr)
            if nk not in gd or nk in visited:
                continue
            visited.add(nk)
            if nk == target:
                return HexDirection(d)
            queue.append((nk, d))
        while queue:
            (q, r), first_d = queue.popleft()
            for dq, dr in _OFFSETS:
                nk = (q + dq, r + dr)
                if nk not in gd or nk in visited:
                    continue
                visited.add(nk)
                if nk == target:
                    return HexDirection(first_d)
                queue.append((nk, first_d))
        return None

    def _turn_toward(self, current: HexDirection, target: HexDirection):
        left = (int(target) - int(current)) % 6
        if left == 0:
            return None
        right = 6 - left
        return Actions.turn_left(left) if left <= right else Actions.turn_right(right)

    def _find_dodge_dir(self, pos, opp_pos, gd):
        """Return a direction to step into that is not in the opponent's LOS."""
        for d, (dq, dr) in enumerate(_OFFSETS):
            nk = (pos[0] + dq, pos[1] + dr)
            if nk not in gd or nk == opp_pos:
                continue
            if self._shooting_dir(opp_pos, nk, gd) is None:
                return HexDirection(d)
        return None

    # ── Main decision ─────────────────────────────────────────────────────────

    def decide(self, game_state: GameState):
        player = game_state.me

        # 1. Stunned — only legal action
        if player.stun > 0:
            return Actions.skip()

        gd = {(t.q, t.r): t for t in game_state.grid}
        pos = (player.position.q, player.position.r)

        # No opponent — just move and paint
        if game_state.opponent is None:
            dq, dr = _OFFSETS[int(player.facing)]
            if (pos[0] + dq, pos[1] + dr) not in gd:
                return Actions.turn_180()
            return Actions.move()

        opp = game_state.opponent
        opp_pos = (opp.position.q, opp.position.r)

        shoot_dir = self._shooting_dir(pos, opp_pos, gd)
        adjacent = opp_pos in {(pos[0] + dq, pos[1] + dr) for dq, dr in _OFFSETS}

        # 2. Paintball: in LOS and ready — turn to face + fire
        if shoot_dir is not None and player.paintball_cooldown == 0:
            turn = self._turn_toward(player.facing, shoot_dir)
            if turn is not None:
                return turn
            return Actions.shoot_paintball()

        # 3. Splat: opponent adjacent and splat ready
        if adjacent and player.splat_cooldown == 0:
            return Actions.splat()

        # 4. Dodge: we're in opponent's LOS and they can shoot us this turn
        opp_threatens = opp.stun == 0 and opp.paintball_cooldown == 0
        if opp_threatens and self._shooting_dir(opp_pos, pos, gd) is not None:
            dodge = self._find_dodge_dir(pos, opp_pos, gd)
            if dodge is not None:
                turn = self._turn_toward(player.facing, dodge)
                if turn is not None:
                    return turn
                return Actions.move()

        # 5. Advance along LOS while paintball cools (close range, maintain aim)
        if shoot_dir is not None:
            turn = self._turn_toward(player.facing, shoot_dir)
            if turn is not None:
                return turn
            dq, dr = _OFFSETS[int(player.facing)]
            next_tile = (pos[0] + dq, pos[1] + dr)
            if next_tile in gd and next_tile != opp_pos:
                return Actions.move()
            return Actions.skip()

        # 6. No LOS — navigate toward opponent
        target_dir = self._bfs_dir(pos, opp_pos, gd)
        if target_dir is not None:
            turn = self._turn_toward(player.facing, target_dir)
            if turn is not None:
                return turn

        # 7. Move forward or bounce at map edge
        dq, dr = _OFFSETS[int(player.facing)]
        if (pos[0] + dq, pos[1] + dr) not in gd:
            return Actions.turn_180()
        return Actions.move()
