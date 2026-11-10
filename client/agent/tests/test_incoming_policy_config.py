import config_store


def test_incoming_policy_keys_are_persisted():
    config_store.load({})
    config_store.update({
        "incoming_policy": "allow_list",
        "incoming_allowed_peers": "rd-a",
        "incoming_denied_peers": "rd-z",
    })
    assert config_store.get("incoming_policy") == "allow_list"
    assert config_store.get("incoming_allowed_peers") == "rd-a"
    assert config_store.get("incoming_denied_peers") == "rd-z"
