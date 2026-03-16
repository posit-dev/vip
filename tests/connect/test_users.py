"""Step definitions for Connect user and group management tests."""

from __future__ import annotations

from pytest_bdd import scenario, then, when


@scenario("test_users.feature", "Admin user exists and has admin privileges")
def test_admin_user():
    pass


@scenario("test_users.feature", "Users can be listed")
def test_list_users():
    pass


@scenario("test_users.feature", "Groups can be listed")
def test_list_groups():
    pass


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


@when("I retrieve the current user profile", target_fixture="current_user")
def retrieve_current_user(connect_client):
    return connect_client.current_user()


@then("the user has admin privileges")
def user_is_admin(current_user):
    assert current_user.get("user_role") == "administrator", (
        f"Expected user_role 'administrator', got {current_user.get('user_role')!r}"
    )


@when("I list all users", target_fixture="user_list")
def list_all_users(connect_client):
    return connect_client.list_users()


@then("the user list is not empty")
def user_list_not_empty(user_list):
    assert user_list, "Connect returned an empty user list"


@then("the test user exists in the user list")
def check_test_user_in_list(user_list, test_username):
    usernames = [u.get("username") for u in user_list]
    assert test_username in usernames, (
        f"Test user {test_username!r} not found in user list: {usernames}"
    )


@when("I list all groups", target_fixture="group_list")
def list_all_groups(connect_client):
    return connect_client.list_groups()


@then("the response is successful")
def groups_response_successful(group_list):
    assert isinstance(group_list, list), (
        f"Expected a list of groups, got {type(group_list).__name__}"
    )
