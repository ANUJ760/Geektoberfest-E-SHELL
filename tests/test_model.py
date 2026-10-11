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

    def test_expanded_natural_language_phrases_are_recognized(self):
        expected = {
            "open mozilla firefox": "open_firefox",
            "open browser": "open_firefox",
            "web browser": "open_firefox",
            "open system calculator": "calculator",
            "open calc": "calculator",
            "how much storage is available": "disk_usage",
            "check storage capacity": "disk_usage",
            "check ram": "memory_usage",
            "how much ram is used": "memory_usage",
            "what is the date": "date_time",
            "what time is it right now": "date_time",
            "how long has this pc been running": "system_uptime",
            "processor specifications": "cpu_info",
            "what username am i using": "current_user",
            "system host name": "hostname",
            "linux distribution": "os_info",
            "check battery": "battery_info",
            "show network adapters": "network_info",
            "show my ip address": "ip_address",
            "who is logged on": "logged_in_users",
            "view environment variables": "environment_info",
            "what shell is running": "shell_info",
            "what version of python": "python_version",
            "system overview": "fastfetch_info",
        }

        for phrase, intent in expected.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(predict_intent(phrase), intent)


if __name__ == "__main__":
    unittest.main()
