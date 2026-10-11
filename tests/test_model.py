import unittest

from model import predict_intent


class IntentPredictionTests(unittest.TestCase):
    def test_new_system_information_intents_are_recognized(self):
        expected = {
            "os info": "os_info",
            "gpu info": "gpu_info",
            "battery info": "battery_info",
            "network info": "network_info",
            "ip address": "ip_address",
            "logged in users": "logged_in_users",
            "running processes": "running_processes",
            "environment info": "environment_info",
            "shell info": "shell_info",
            "python version": "python_version",
            "package manager info": "package_manager_info",
            "fastfetch info": "fastfetch_info",
            "version": "version",
            "show version": "version",
            "project version": "version",
            "edit notes.py": "edit_file",
            "open notes.py in nano": "edit_file",
            "open notes.py in vim": "edit_file",
            "make script.sh executable": "make_executable",
            "run hello.py": "run_file",
        }

        for phrase, intent in expected.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(predict_intent(phrase), intent)

    def test_existing_core_intents_still_work_after_expansion(self):
        expected = {
            "disk usage": "disk_usage",
            "disk info": "disk_usage",
            "memory usage": "memory_usage",
            "cpu info": "cpu_info",
            "kernel info": "kernel_info",
        }

        for phrase, intent in expected.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(predict_intent(phrase), intent)


if __name__ == "__main__":
    unittest.main()
