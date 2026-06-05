"""Unit tests for app/permissions.py — role/action permission model."""
import pytest

from app.permissions import ACTION_MIN_ROLE, ROLE_LEVEL, can, level, permissions_for


class TestLevel:
    def test_known_roles(self):
        assert level("officer") == 1
        assert level("admin") == 2

    def test_unknown_role_returns_zero(self):
        assert level("guest") == 0
        assert level("") == 0


class TestCan:
    @pytest.mark.parametrize("action", list(ACTION_MIN_ROLE.keys()))
    def test_admin_can_do_everything(self, action):
        assert can("admin", action) is True

    @pytest.mark.parametrize("action", [
        "locate", "scan", "give_title", "rotation", "change_rank",
    ])
    def test_officer_can_do_officer_actions(self, action):
        assert can("officer", action) is True

    def test_unknown_action_defaults_to_admin_required(self):
        # Actions not listed in ACTION_MIN_ROLE require admin level.
        assert can("admin", "unknown_action") is True
        assert can("officer", "unknown_action") is False

    def test_unknown_role_cannot_do_anything(self):
        assert can("guest", "locate") is False
        assert can("", "scan") is False


class TestPermissionsFor:
    def test_admin_permissions(self):
        perms = permissions_for("admin")
        assert all(perms[a] for a in ACTION_MIN_ROLE)
        assert perms["change_rank_r5"] is True

    def test_officer_permissions(self):
        perms = permissions_for("officer")
        assert perms["locate"] is True
        assert perms["scan"] is True
        assert perms["give_title"] is True
        assert perms["change_rank"] is True
        # R5 promotion is admin-only.
        assert perms["change_rank_r5"] is False

    def test_guest_permissions_all_false(self):
        perms = permissions_for("guest")
        assert all(not perms[a] for a in ACTION_MIN_ROLE)
        assert perms["change_rank_r5"] is False
