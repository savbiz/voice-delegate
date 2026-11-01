"""Native scaffold permissions and packaged-app boundaries without SDKs or providers."""

import json
import plistlib
import re
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]


def test_native_projects_request_audio_without_camera_or_cleartext() -> None:
    ios = plistlib.loads((ROOT / "frontend/ios/App/App/Info.plist").read_bytes())
    assert "microphone" in ios["NSMicrophoneUsageDescription"]
    assert "NSCameraUsageDescription" not in ios
    assert "NSAllowsArbitraryLoads" not in ios.get("NSAppTransportSecurity", {})
    android = ElementTree.parse(ROOT / "frontend/android/app/src/main/AndroidManifest.xml")
    prefix = "{http://schemas.android.com/apk/res/android}"
    permissions = {node.get(prefix + "name") for node in android.findall("uses-permission")}
    assert permissions == {
        "android.permission.INTERNET",
        "android.permission.RECORD_AUDIO",
        "android.permission.MODIFY_AUDIO_SETTINGS",
    }
    application = android.find("application")
    assert application is not None
    assert application.get(prefix + "usesCleartextTraffic") == "false"
    assert application.get(prefix + "allowBackup") == "false"


def test_native_version_comes_from_frontend_package() -> None:
    version = json.loads((ROOT / "frontend/package.json").read_text())["version"]
    ios = (ROOT / "frontend/ios/App/App.xcodeproj/project.pbxproj").read_text()
    assert set(re.findall(r"MARKETING_VERSION = ([^;]+);", ios)) == {version}
    android = (ROOT / "frontend/android/app/build.gradle").read_text()
    assert "parse(file('../../package.json')).version" in android


def test_android_instrumented_test_targets_actual_application_id() -> None:
    project = ROOT / "frontend/android/app"
    build = (project / "build.gradle").read_text()
    application = re.search(r'applicationId "([^"]+)"', build)
    assert application is not None
    test = (
        project / "src/androidTest/java/com/getcapacitor/myapp/ExampleInstrumentedTest.java"
    ).read_text()
    expected = re.search(r'assertEquals\("([^"]+)", appContext.getPackageName\(\)\)', test)
    assert expected is not None
    assert expected[1] == application[1]


def test_android_theme_color_references_are_defined_by_the_app() -> None:
    values = ROOT / "frontend/android/app/src/main/res/values"
    theme = ElementTree.parse(values / "styles.xml")
    colors = ElementTree.parse(values / "colors.xml")
    references = {
        item.text.removeprefix("@color/")
        for item in theme.findall(".//item")
        if item.text and item.text.startswith("@color/")
    }
    declarations = {color.get("name") for color in colors.findall("color")}
    assert references and references <= declarations
