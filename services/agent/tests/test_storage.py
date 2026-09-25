from app import storage


class TestUploadTarget:
    def test_local_mode_returns_direct_post_url(self, monkeypatch):
        monkeypatch.setenv("STORAGE_MODE", "local")
        monkeypatch.setenv("PUBLIC_UPLOAD_BASE", "http://localhost:8080/gcs")

        target = storage.upload_target("uid-1", "obj-1")

        assert target.method == "POST"
        assert target.object == "receipts/uid-1/obj-1.jpg"
        assert target.url.startswith("http://localhost:8080/gcs/upload/storage/v1/b/")
        assert "receipts/uid-1/obj-1.jpg" in target.url

    def test_object_name_is_namespaced_per_user(self, monkeypatch):
        monkeypatch.setenv("STORAGE_MODE", "local")
        monkeypatch.setenv("PUBLIC_UPLOAD_BASE", "http://localhost:8080/gcs")

        target_a = storage.upload_target("uid-a", "obj-1")
        target_b = storage.upload_target("uid-b", "obj-1")

        assert target_a.object != target_b.object
