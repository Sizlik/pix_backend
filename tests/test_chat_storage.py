from manager.chat_storage import MinioObjectStorage


class FakeMinio:
    def __init__(self):
        self.buckets = set()
        self.objects = {}

    def bucket_exists(self, bucket):
        return bucket in self.buckets

    def make_bucket(self, bucket):
        self.buckets.add(bucket)

    def put_object(self, bucket, key, stream, length, content_type):
        self.objects[(bucket, key)] = (
            stream.read(),
            length,
            content_type,
        )

    def get_object(self, bucket, key):
        content = self.objects[(bucket, key)][0]

        class Response:
            data = content

            def close(self):
                return None

            def release_conn(self):
                return None

        return Response()

    def remove_object(self, bucket, key):
        self.objects.pop((bucket, key), None)


async def test_minio_adapter_owns_bucket_and_round_trips_bytes():
    client = FakeMinio()
    storage = MinioObjectStorage(client=client, bucket="pix-order-chat")

    await storage.ensure_bucket()
    await storage.put("orders/o/messages/m/a.txt", b"hello", "text/plain")

    assert await storage.read("orders/o/messages/m/a.txt") == b"hello"
    assert client.objects[("pix-order-chat", "orders/o/messages/m/a.txt")][1:] == (5, "text/plain")
    await storage.delete("orders/o/messages/m/a.txt")
    assert client.objects == {}
