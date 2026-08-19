from r2sync.core.models import R2BucketInfo, R2Credentials
from r2sync.core.r2_client import CloudflareR2Client


def test_cloudflare_urls():
    url_dash = CloudflareR2Client.get_dashboard_url("acc123")
    assert url_dash == "https://dash.cloudflare.com/acc123/r2/overview"

    url_tokens = CloudflareR2Client.get_api_tokens_url("acc123")
    assert url_tokens == "https://dash.cloudflare.com/acc123/r2/api-tokens"

    url_bucket = CloudflareR2Client.get_bucket_url("my-photos", "acc123")
    assert url_bucket == "https://dash.cloudflare.com/acc123/r2/default/buckets/my-photos"

    url_billing = CloudflareR2Client.get_billing_url("acc123")
    assert url_billing == "https://dash.cloudflare.com/acc123/billing"


def test_r2_bucket_info():
    info = R2BucketInfo(name="backup-bucket", location="auto", object_count=150, size_bytes=10485760)
    data = info.to_dict()
    assert data["name"] == "backup-bucket"
    assert data["object_count"] == 150
    assert data["size_bytes"] == 10485760
