"""Immutable inputs for a nonauthoritative, source-built stdlib experiment."""

SOURCE_URL = "https://github.com/gitleaks/gitleaks.git"
SOURCE_COMMIT = "83d9cd684c87d95d656c1458ef04895a7f1cbd8e"
SOURCE_TREE = "18ffe9bab74b97087f58f56c9cfe0fe28ddc97a6"
SOURCE_INVENTORIES = {
    "original": "2e881b3c226bc07363f3f5e427a812936a26b6748f4a818ac6084f5342e74aa7",
    "control": "62dab7e791122867fdbeecd7e7bbf7e582b44a8fc365644007410a0f2ecf8429",
    "candidate": "d4f30010ac12bef0c8f3025c829a9e7c9b987327617beb44a769bf7358c8dd4d",
}
PATCHES = {
    "control": (
        "gitleaks-rule-profile.patch",
        "d7d8e053f72e4fb647f5b5e8bcb9ca51ff7f42bfbb62aafd006603ffe9265072",
    ),
    "candidate": (
        "gitleaks-optional-prefix.patch",
        "e6a984ffb8a4b7f846952ab78fdcbbc281c60cb5440e86a0af8da1ddebe1964f",
    ),
}
UNCHANGED_FILES = {
    "config/gitleaks.toml": "e163e53b9e7e8a8511e77271e2b323ed057759542a6d988258afe3a1fa329caf",
    "go.mod": "607c140abf2a872e70423972d4dfc7fa658ebe10365d0ea995269ed292add7a3",
    "go.sum": "3fd66952713338b561c71c7ed608c5cce41355a7594c4eb8ffb4303abae29ccd",
}
GO_VERSION = "go1.24.11"
GO_ARCHIVE_URL = "https://go.dev/dl/go1.24.11.linux-amd64.tar.gz"
GO_ARCHIVE_SHA256 = "bceca00afaac856bc48b4cc33db7cd9eb383c81811379faed3bdbc80edb0af65"
GO_EXECUTABLE_SHA256 = "6728adbfea3a232a1e81270dc23da929258f5daf185422140f68dc081bb52504"
GO_TOOLCHAIN_SHA256 = "e921964a4f1a06a023b62d270aa681530b7a95ee29d0676f4f0043acbf77cee9"
GO_TOOLCHAIN_FILES = 14_178
GO_TOOLCHAIN_BYTES = 253_338_050
BUILD_ARGUMENTS = (
    "build",
    "-mod=readonly",
    "-trimpath",
    "-buildvcs=false",
    "-ldflags",
    "-X=github.com/zricethezav/gitleaks/v8/version.Version=v8.30.1",
)
