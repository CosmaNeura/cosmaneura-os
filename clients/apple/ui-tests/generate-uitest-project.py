#!/usr/bin/env python3
"""Generate a minimal UI-test-only Xcode project for CosmasSyntheticUITests."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
TESTS = ROOT / "CosmasSyntheticUITests"
PROJECT = ROOT / "CosmasSyntheticUITests.xcodeproj"
SOURCES = (
    "VisitTimerAndChiefIconUITests.swift",
    "MicrophonePermissionUITests.swift",
)

# Stable IDs so the generator is deterministic across reruns.
PROJECT_ID = "A10000000000000000000001"
TARGET_ID = "A10000000000000000000002"
SOURCES_PHASE = "A10000000000000000000003"
RESOURCES_PHASE = "A10000000000000000000004"
FRAMEWORKS_PHASE = "A10000000000000000000005"
CONFIG_LIST_PROJECT = "A10000000000000000000006"
CONFIG_LIST_TARGET = "A10000000000000000000007"
DEBUG_PROJECT = "A10000000000000000000008"
RELEASE_PROJECT = "A10000000000000000000009"
DEBUG_TARGET = "A1000000000000000000000A"
RELEASE_TARGET = "A1000000000000000000000B"
TESTS_GROUP = "A1000000000000000000000D"
PRODUCTS_GROUP = "A1000000000000000000000E"
MAIN_GROUP = "A1000000000000000000000F"
PRODUCT_REF = "A10000000000000000000010"
# Per-source fileRef / buildFile pairs (even indices after the fixed block).
SOURCE_IDS = (
    ("A1000000000000000000000C", "A10000000000000000000011"),
    ("A10000000000000000000012", "A10000000000000000000013"),
)


def main() -> None:
    assert len(SOURCES) == len(SOURCE_IDS)
    for name in SOURCES:
        assert (TESTS / name).is_file(), name

    build_files = "\n".join(
        f"\t\t{build} /* {name} in Sources */ = {{isa = PBXBuildFile; fileRef = {ref} /* {name} */; }};"
        for (ref, build), name in zip(SOURCE_IDS, SOURCES)
    )
    file_refs = "\n".join(
        f'\t\t{ref} /* {name} */ = {{isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = {name}; sourceTree = "<group>"; }};'
        for (ref, _), name in zip(SOURCE_IDS, SOURCES)
    )
    group_children = "\n".join(
        f"\t\t\t\t{ref} /* {name} */,"
        for (ref, _), name in zip(SOURCE_IDS, SOURCES)
    )
    sources_phase_files = "\n".join(
        f"\t\t\t\t{build} /* {name} in Sources */,"
        for (_, build), name in zip(SOURCE_IDS, SOURCES)
    )

    pbx = f"""// !$*UTF8*$!
{{
	archiveVersion = 1;
	classes = {{}};
	objectVersion = 56;
	objects = {{

/* Begin PBXBuildFile section */
{build_files}
/* End PBXBuildFile section */

/* Begin PBXFileReference section */
{file_refs}
		{PRODUCT_REF} /* CosmasSyntheticUITests.xctest */ = {{isa = PBXFileReference; explicitFileType = wrapper.cfbundle; includeInIndex = 0; path = CosmasSyntheticUITests.xctest; sourceTree = BUILT_PRODUCTS_DIR; }};
/* End PBXFileReference section */

/* Begin PBXFrameworksBuildPhase section */
		{FRAMEWORKS_PHASE} /* Frameworks */ = {{
			isa = PBXFrameworksBuildPhase;
			buildActionMask = 2147483647;
			files = (
			);
			runOnlyForDeploymentPostprocessing = 0;
		}};
/* End PBXFrameworksBuildPhase section */

/* Begin PBXGroup section */
		{MAIN_GROUP} = {{
			isa = PBXGroup;
			children = (
				{TESTS_GROUP} /* CosmasSyntheticUITests */,
				{PRODUCTS_GROUP} /* Products */,
			);
			sourceTree = "<group>";
		}};
		{TESTS_GROUP} /* CosmasSyntheticUITests */ = {{
			isa = PBXGroup;
			children = (
{group_children}
			);
			path = CosmasSyntheticUITests;
			sourceTree = "<group>";
		}};
		{PRODUCTS_GROUP} /* Products */ = {{
			isa = PBXGroup;
			children = (
				{PRODUCT_REF} /* CosmasSyntheticUITests.xctest */,
			);
			name = Products;
			sourceTree = "<group>";
		}};
/* End PBXGroup section */

/* Begin PBXNativeTarget section */
		{TARGET_ID} /* CosmasSyntheticUITests */ = {{
			isa = PBXNativeTarget;
			buildConfigurationList = {CONFIG_LIST_TARGET} /* Build configuration list for PBXNativeTarget "CosmasSyntheticUITests" */;
			buildPhases = (
				{SOURCES_PHASE} /* Sources */,
				{FRAMEWORKS_PHASE} /* Frameworks */,
				{RESOURCES_PHASE} /* Resources */,
			);
			buildRules = (
			);
			dependencies = (
			);
			name = CosmasSyntheticUITests;
			productName = CosmasSyntheticUITests;
			productReference = {PRODUCT_REF} /* CosmasSyntheticUITests.xctest */;
			productType = "com.apple.product-type.bundle.ui-testing";
		}};
/* End PBXNativeTarget section */

/* Begin PBXProject section */
		{PROJECT_ID} /* Project object */ = {{
			isa = PBXProject;
			attributes = {{
				BuildIndependentTargetsInParallel = 1;
				LastSwiftUpdateCheck = 1600;
				LastUpgradeCheck = 1600;
				TargetAttributes = {{
					{TARGET_ID} = {{
						CreatedOnToolsVersion = 16.0;
					}};
				}};
			}};
			buildConfigurationList = {CONFIG_LIST_PROJECT} /* Build configuration list for PBXProject "CosmasSyntheticUITests" */;
			compatibilityVersion = "Xcode 14.0";
			developmentRegion = en;
			hasScannedForEncodings = 0;
			knownRegions = (
				en,
				Base,
			);
			mainGroup = {MAIN_GROUP};
			productRefGroup = {PRODUCTS_GROUP} /* Products */;
			projectDirPath = "";
			projectRoot = "";
			targets = (
				{TARGET_ID} /* CosmasSyntheticUITests */,
			);
		}};
/* End PBXProject section */

/* Begin PBXResourcesBuildPhase section */
		{RESOURCES_PHASE} /* Resources */ = {{
			isa = PBXResourcesBuildPhase;
			buildActionMask = 2147483647;
			files = (
			);
			runOnlyForDeploymentPostprocessing = 0;
		}};
/* End PBXResourcesBuildPhase section */

/* Begin PBXSourcesBuildPhase section */
		{SOURCES_PHASE} /* Sources */ = {{
			isa = PBXSourcesBuildPhase;
			buildActionMask = 2147483647;
			files = (
{sources_phase_files}
			);
			runOnlyForDeploymentPostprocessing = 0;
		}};
/* End PBXSourcesBuildPhase section */

/* Begin XCBuildConfiguration section */
		{DEBUG_PROJECT} /* Debug */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				ALWAYS_SEARCH_USER_PATHS = NO;
				CLANG_ENABLE_MODULES = YES;
				COPY_PHASE_STRIP = NO;
				DEBUG_INFORMATION_FORMAT = dwarf;
				ENABLE_TESTABILITY = YES;
				GCC_DYNAMIC_NO_PIC = NO;
				IPHONEOS_DEPLOYMENT_TARGET = 17.0;
				ONLY_ACTIVE_ARCH = YES;
				SDKROOT = iphoneos;
				SWIFT_ACTIVE_COMPILATION_CONDITIONS = DEBUG;
				SWIFT_OPTIMIZATION_LEVEL = "-Onone";
			}};
			name = Debug;
		}};
		{RELEASE_PROJECT} /* Release */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				ALWAYS_SEARCH_USER_PATHS = NO;
				CLANG_ENABLE_MODULES = YES;
				COPY_PHASE_STRIP = NO;
				DEBUG_INFORMATION_FORMAT = "dwarf-with-dsym";
				IPHONEOS_DEPLOYMENT_TARGET = 17.0;
				SDKROOT = iphoneos;
				SWIFT_COMPILATION_MODE = wholemodule;
			}};
			name = Release;
		}};
		{DEBUG_TARGET} /* Debug */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				CODE_SIGNING_ALLOWED = NO;
				CODE_SIGNING_REQUIRED = NO;
				GENERATE_INFOPLIST_FILE = YES;
				IPHONEOS_DEPLOYMENT_TARGET = 17.0;
				LD_RUNPATH_SEARCH_PATHS = (
					"$(inherited)",
					"@executable_path/Frameworks",
					"@loader_path/Frameworks",
				);
				PRODUCT_BUNDLE_IDENTIFIER = com.cosmasos.synthetic.uitests;
				PRODUCT_NAME = "$(TARGET_NAME)";
				SDKROOT = iphonesimulator;
				SUPPORTED_PLATFORMS = iphonesimulator;
				SWIFT_EMIT_LOC_STRINGS = NO;
				SWIFT_VERSION = 5.0;
				TARGETED_DEVICE_FAMILY = "1,2";
			}};
			name = Debug;
		}};
		{RELEASE_TARGET} /* Release */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				CODE_SIGNING_ALLOWED = NO;
				CODE_SIGNING_REQUIRED = NO;
				GENERATE_INFOPLIST_FILE = YES;
				IPHONEOS_DEPLOYMENT_TARGET = 17.0;
				LD_RUNPATH_SEARCH_PATHS = (
					"$(inherited)",
					"@executable_path/Frameworks",
					"@loader_path/Frameworks",
				);
				PRODUCT_BUNDLE_IDENTIFIER = com.cosmasos.synthetic.uitests;
				PRODUCT_NAME = "$(TARGET_NAME)";
				SDKROOT = iphonesimulator;
				SUPPORTED_PLATFORMS = iphonesimulator;
				SWIFT_EMIT_LOC_STRINGS = NO;
				SWIFT_VERSION = 5.0;
				TARGETED_DEVICE_FAMILY = "1,2";
			}};
			name = Release;
		}};
/* End XCBuildConfiguration section */

/* Begin XCConfigurationList section */
		{CONFIG_LIST_PROJECT} /* Build configuration list for PBXProject "CosmasSyntheticUITests" */ = {{
			isa = XCConfigurationList;
			buildConfigurations = (
				{DEBUG_PROJECT} /* Debug */,
				{RELEASE_PROJECT} /* Release */,
			);
			defaultConfigurationIsVisible = 0;
			defaultConfigurationName = Release;
		}};
		{CONFIG_LIST_TARGET} /* Build configuration list for PBXNativeTarget "CosmasSyntheticUITests" */ = {{
			isa = XCConfigurationList;
			buildConfigurations = (
				{DEBUG_TARGET} /* Debug */,
				{RELEASE_TARGET} /* Release */,
			);
			defaultConfigurationIsVisible = 0;
			defaultConfigurationName = Release;
		}};
/* End XCConfigurationList section */
	}};
	rootObject = {PROJECT_ID} /* Project object */;
}}
"""
    PROJECT.mkdir(parents=True, exist_ok=True)
    (PROJECT / "project.pbxproj").write_text(pbx)
    scheme_dir = PROJECT / "xcshareddata/xcschemes"
    scheme_dir.mkdir(parents=True, exist_ok=True)
    (scheme_dir / "CosmasSyntheticUITests.xcscheme").write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<Scheme
   LastUpgradeVersion = "1600"
   version = "1.7">
   <BuildAction
      parallelizeBuildables = "YES"
      buildImplicitDependencies = "YES">
      <BuildActionEntries>
         <BuildActionEntry
            buildForTesting = "YES"
            buildForRunning = "YES"
            buildForProfiling = "NO"
            buildForArchiving = "NO"
            buildForAnalyzing = "NO">
            <BuildableReference
               BuildableIdentifier = "primary"
               BlueprintIdentifier = "{TARGET_ID}"
               BuildableName = "CosmasSyntheticUITests.xctest"
               BlueprintName = "CosmasSyntheticUITests"
               ReferencedContainer = "container:CosmasSyntheticUITests.xcodeproj">
            </BuildableReference>
         </BuildActionEntry>
      </BuildActionEntries>
   </BuildAction>
   <TestAction
      buildConfiguration = "Debug"
      selectedDebuggerIdentifier = "Xcode.DebuggerFoundation.Debugger.LLDB"
      selectedLauncherIdentifier = "Xcode.DebuggerFoundation.Launcher.LLDB"
      shouldUseLaunchSchemeArgsEnv = "YES">
      <Testables>
         <TestableReference
            skipped = "NO"
            parallelizable = "NO">
            <BuildableReference
               BuildableIdentifier = "primary"
               BlueprintIdentifier = "{TARGET_ID}"
               BuildableName = "CosmasSyntheticUITests.xctest"
               BlueprintName = "CosmasSyntheticUITests"
               ReferencedContainer = "container:CosmasSyntheticUITests.xcodeproj">
            </BuildableReference>
         </TestableReference>
      </Testables>
   </TestAction>
   <LaunchAction
      buildConfiguration = "Debug"
      selectedDebuggerIdentifier = "Xcode.DebuggerFoundation.Debugger.LLDB"
      selectedLauncherIdentifier = "Xcode.DebuggerFoundation.Launcher.LLDB"
      launchStyle = "0"
      useCustomWorkingDirectory = "NO"
      ignoresPersistentStateOnLaunch = "NO"
      debugDocumentVersioning = "YES"
      debugServiceExtension = "internal"
      allowLocationSimulation = "YES">
   </LaunchAction>
   <ProfileAction
      buildConfiguration = "Release"
      shouldUseLaunchSchemeArgsEnv = "YES"
      savedToolIdentifier = ""
      useCustomWorkingDirectory = "NO"
      debugDocumentVersioning = "YES">
   </ProfileAction>
   <AnalyzeAction
      buildConfiguration = "Debug">
   </AnalyzeAction>
   <ArchiveAction
      buildConfiguration = "Release"
      revealArchiveInOrganizer = "YES">
   </ArchiveAction>
</Scheme>
"""
    )
    print(f"Wrote {PROJECT}")


if __name__ == "__main__":
    main()
