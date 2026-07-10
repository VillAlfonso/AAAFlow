import unittest
from unittest import mock

from app import youtube


class YouTubeEnvTests(unittest.TestCase):
    def test_effective_youtube_creds_falls_back_to_config(self):
        with mock.patch.object(youtube.config, "YOUTUBE", {
            "client_id": "env-client-id",
            "client_secret": "env-client-secret",
        }):
            creds = youtube._effective_youtube_creds({"youtube": {}})

        self.assertEqual(creds["client_id"], "env-client-id")
        self.assertEqual(creds["client_secret"], "env-client-secret")


if __name__ == "__main__":
    unittest.main()
