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

    def test_signed_url_is_made_for_the_uploads_content_type(self, monkeypatch):
        # A V4 signed PUT only accepts the Content-Type it was signed for — signing
        # every upload as image/jpeg made PDF receipts fail in production.
        monkeypatch.delenv("STORAGE_MODE", raising=False)
        signed = {}

        class FakeBlob:
            def generate_signed_url(self, **kwargs):
                signed.update(kwargs)
                return "https://storage.example/signed"

        class FakeClient:
            def bucket(self, name):
                return type("B", (), {"blob": lambda self, n: FakeBlob()})()

        monkeypatch.setattr(storage.storage, "Client", FakeClient)

        target = storage.upload_target("uid-1", "obj-1", "application/pdf")

        assert target.method == "PUT"
        assert signed["content_type"] == "application/pdf"
