import unittest
from unittest.mock import patch, MagicMock
import os
import json
import tempfile
from pathlib import Path
from src.api import RomMClient
from src.config import ConfigManager

class TestKeyringIntegration(unittest.TestCase):
    def setUp(self):
        # Create a temporary config dir and file
        self.test_dir = tempfile.TemporaryDirectory()
        self.home_path = Path(self.test_dir.name)
        
        # Mock Path.home() to point to our temp dir
        self.home_patcher = patch("pathlib.Path.home", return_value=self.home_path)
        self.home_patcher.start()
        
        self.config = ConfigManager()
        # Re-set these to be absolutely sure they point to our temp dir
        self.config.config_dir = self.home_path / ".wingosy"
        self.config.config_file = self.config.config_dir / "config.json"
        self.config.config_dir.mkdir(parents=True, exist_ok=True)
        self.config.save() # Create initial file
        self.config_path = self.config.config_file

    def tearDown(self):
        self.home_patcher.stop()
        self.test_dir.cleanup()

    @patch("keyring.get_password")
    @patch("keyring.set_password")
    def test_token_migration_from_config(self, mock_set, mock_get):
        # Create an old-style config with a plaintext token
        old_config = {
            "host": "http://localhost:8285",
            "username": "admin",
            "token": "old-plaintext-token"
        }
        with open(self.config_path, "w") as f:
            json.dump(old_config, f)
            
        # Loading the config should trigger migration
        self.config.load()
        
        # Verify keyring.set_password was called
        mock_set.assert_called_with("wingosy", "auth_token", "old-plaintext-token")
        
        # Verify token is removed from memory data
        self.assertIsNone(self.config.get("token"))
        
        # Verify token is removed from the file
        with open(self.config_path, "r") as f:
            saved_data = json.load(f)
            self.assertNotIn("token", saved_data)

    @patch("keyring.set_password")
    @patch("requests.post")
    def test_login_saves_to_keyring(self, mock_post, mock_set):
        # Mock successful login response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": "new-secure-token"}
        mock_post.return_value = mock_response
        
        client = RomMClient("http://localhost:8285", config=self.config)
        success, token = client.login("user", "pass")
        
        self.assertTrue(success)
        self.assertEqual(token, "new-secure-token")
        
        # Verify keyring was updated
        mock_set.assert_called_with("wingosy", "auth_token", "new-secure-token")
        
        # Verify it did NOT save to config.json
        with open(self.config_path, "r") as f:
            saved_data = json.load(f)
            self.assertNotIn("token", saved_data)

    @patch("keyring.get_password", return_value="secure-token-from-keyring")
    def test_startup_retrieves_from_keyring(self, mock_get):
        client = RomMClient("http://localhost:8285", config=self.config)
        self.assertEqual(client.token, "secure-token-from-keyring")
        mock_get.assert_called_with("wingosy", "auth_token")

    @patch("keyring.get_password", side_effect=Exception("Keyring locked"))
    def test_keyring_failure_fallbacks_to_config(self, mock_get):
        # Put a token in config manually (simulating a failed migration or manual entry)
        self.config.data["token"] = "fallback-token"
        
        client = RomMClient("http://localhost:8285", config=self.config)
        
        # Should return the fallback token despite keyring error
        self.assertEqual(client.token, "fallback-token")

    @patch("keyring.delete_password")
    def test_logout_removes_from_keyring(self, mock_delete):
        client = RomMClient("http://localhost:8285", config=self.config)
        client.token = "some-token"
        
        client.logout()
        
        self.assertIsNone(client.token)
        mock_delete.assert_called_with("wingosy", "auth_token")

if __name__ == "__main__":
    unittest.main()
