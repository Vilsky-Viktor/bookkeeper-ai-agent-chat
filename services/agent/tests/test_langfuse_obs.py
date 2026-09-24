from app.langfuse_obs import mask_for_export


class TestMaskForExport:
    def test_hashes_description_instead_of_exporting_raw_text(self):
        result = mask_for_export("uid-1", "coffee at Starbucks")
        assert "description_hash" in result
        assert result["description_hash"] != "coffee at Starbucks"
        assert len(result["description_hash"]) == 12

    def test_none_description_stays_none(self):
        result = mask_for_export("uid-1", None)
        assert result["description_hash"] is None

    def test_same_description_hashes_identically(self):
        assert (
            mask_for_export("uid-1", "coffee")["description_hash"]
            == mask_for_export("uid-2", "coffee")["description_hash"]
        )

    def test_different_description_hashes_differently(self):
        assert (
            mask_for_export("uid-1", "coffee")["description_hash"]
            != mask_for_export("uid-1", "tea")["description_hash"]
        )
