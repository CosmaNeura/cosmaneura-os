import { isAbsolute, resolve, sep } from "node:path";
const RENDERER_ASSETS = Object.freeze({
  "/assets/InboxAnalysisPanel-D0vfKVKw.js": {
    "file": "public/assets/InboxAnalysisPanel-D0vfKVKw.js",
    "contentType": "text/javascript"
  },
  "/assets/MembershipAnalysisPanel-BOLQJKwF.js": {
    "file": "public/assets/MembershipAnalysisPanel-BOLQJKwF.js",
    "contentType": "text/javascript"
  },
  "/assets/PracticeHub-DX_rwJ7F.js": {
    "file": "public/assets/PracticeHub-DX_rwJ7F.js",
    "contentType": "text/javascript"
  },
  "/assets/PracticeHub-DhZuKNls.css": {
    "file": "public/assets/PracticeHub-DhZuKNls.css",
    "contentType": "text/css"
  },
  "/assets/PracticeWork-CjQjH9GN.js": {
    "file": "public/assets/PracticeWork-CjQjH9GN.js",
    "contentType": "text/javascript"
  },
  "/assets/ResearchWorkspace-B0AELHcz.css": {
    "file": "public/assets/ResearchWorkspace-B0AELHcz.css",
    "contentType": "text/css"
  },
  "/assets/ResearchWorkspace-vIF-mmHm.js": {
    "file": "public/assets/ResearchWorkspace-vIF-mmHm.js",
    "contentType": "text/javascript"
  },
  "/assets/browser-microphone-source-DaDwdq9E.js": {
    "file": "public/assets/browser-microphone-source-DaDwdq9E.js",
    "contentType": "text/javascript"
  },
  "/assets/capacitor-ios-native-pcm-bridge-B_0VxfZr.js": {
    "file": "public/assets/capacitor-ios-native-pcm-bridge-B_0VxfZr.js",
    "contentType": "text/javascript"
  },
  "/assets/index-CZTZx_gC.js": {
    "file": "public/assets/index-CZTZx_gC.js",
    "contentType": "text/javascript"
  },
  "/assets/index-CilUvGHQ.css": {
    "file": "public/assets/index-CilUvGHQ.css",
    "contentType": "text/css"
  },
  "/assets/index-DHvX7osj.js": {
    "file": "public/assets/index-DHvX7osj.js",
    "contentType": "text/javascript"
  },
  "/assets/pcm-capture-worklet-BTT4elkG.js": {
    "file": "public/assets/pcm-capture-worklet-BTT4elkG.js",
    "contentType": "text/javascript"
  },
  "/assets/private-recording-desktop-yBgEwDp6.js": {
    "file": "public/assets/private-recording-desktop-yBgEwDp6.js",
    "contentType": "text/javascript"
  },
  "/assets/private-recording-source-aV5iZOS7.js": {
    "file": "public/assets/private-recording-source-aV5iZOS7.js",
    "contentType": "text/javascript"
  },
  "/assets/source-authority-DQBWj5m2.js": {
    "file": "public/assets/source-authority-DQBWj5m2.js",
    "contentType": "text/javascript"
  },
  "/bots/chief.png": {
    "file": "public/bots/chief.png",
    "contentType": "image/png"
  },
  "/bots/follow-up.png": {
    "file": "public/bots/follow-up.png",
    "contentType": "image/png"
  },
  "/bots/motion/chief-intro.webp": {
    "file": "public/bots/motion/chief-intro.webp",
    "contentType": "image/webp"
  },
  "/bots/motion/chief-work.webp": {
    "file": "public/bots/motion/chief-work.webp",
    "contentType": "image/webp"
  },
  "/bots/motion/follow-up-intro.webp": {
    "file": "public/bots/motion/follow-up-intro.webp",
    "contentType": "image/webp"
  },
  "/bots/motion/follow-up-work.webp": {
    "file": "public/bots/motion/follow-up-work.webp",
    "contentType": "image/webp"
  },
  "/bots/motion/scribe-intro.webp": {
    "file": "public/bots/motion/scribe-intro.webp",
    "contentType": "image/webp"
  },
  "/bots/motion/scribe-work.webp": {
    "file": "public/bots/motion/scribe-work.webp",
    "contentType": "image/webp"
  },
  "/bots/motion/visit-prep-intro.webp": {
    "file": "public/bots/motion/visit-prep-intro.webp",
    "contentType": "image/webp"
  },
  "/bots/motion/visit-prep-work.webp": {
    "file": "public/bots/motion/visit-prep-work.webp",
    "contentType": "image/webp"
  },
  "/bots/research.png": {
    "file": "public/bots/research.png",
    "contentType": "image/png"
  },
  "/bots/scribe.png": {
    "file": "public/bots/scribe.png",
    "contentType": "image/png"
  },
  "/bots/visit-prep.png": {
    "file": "public/bots/visit-prep.png",
    "contentType": "image/png"
  },
  "/cosmas-beta-features.json": {
    "file": "public/cosmas-beta-features.json",
    "contentType": "application/json"
  },
  "/cosmas-workspace-build.json": {
    "file": "public/cosmas-workspace-build.json",
    "contentType": "application/json"
  },
  "/index.html": {
    "file": "public/index.html",
    "contentType": "text/html"
  },
  "/startup.css": {
    "file": "public/startup.css",
    "contentType": "text/css"
  },
  "/vendor/pdfjs-6.2.108/LICENSE": {
    "file": "public/vendor/pdfjs-6.2.108/LICENSE",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/SOURCE_MANIFEST.json": {
    "file": "public/vendor/pdfjs-6.2.108/SOURCE_MANIFEST.json",
    "contentType": "application/json"
  },
  "/vendor/pdfjs-6.2.108/cmaps/78-EUC-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/78-EUC-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/78-EUC-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/78-EUC-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/78-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/78-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/78-RKSJ-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/78-RKSJ-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/78-RKSJ-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/78-RKSJ-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/78-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/78-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/78ms-RKSJ-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/78ms-RKSJ-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/78ms-RKSJ-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/78ms-RKSJ-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/83pv-RKSJ-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/83pv-RKSJ-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/90ms-RKSJ-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/90ms-RKSJ-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/90ms-RKSJ-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/90ms-RKSJ-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/90msp-RKSJ-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/90msp-RKSJ-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/90msp-RKSJ-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/90msp-RKSJ-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/90pv-RKSJ-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/90pv-RKSJ-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/90pv-RKSJ-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/90pv-RKSJ-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Add-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Add-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Add-RKSJ-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Add-RKSJ-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Add-RKSJ-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Add-RKSJ-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Add-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Add-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-CNS1-0.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-CNS1-0.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-CNS1-1.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-CNS1-1.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-CNS1-2.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-CNS1-2.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-CNS1-3.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-CNS1-3.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-CNS1-4.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-CNS1-4.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-CNS1-5.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-CNS1-5.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-CNS1-6.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-CNS1-6.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-CNS1-UCS2.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-CNS1-UCS2.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-GB1-0.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-GB1-0.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-GB1-1.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-GB1-1.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-GB1-2.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-GB1-2.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-GB1-3.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-GB1-3.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-GB1-4.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-GB1-4.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-GB1-5.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-GB1-5.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-GB1-UCS2.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-GB1-UCS2.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-Japan1-0.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-Japan1-0.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-Japan1-1.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-Japan1-1.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-Japan1-2.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-Japan1-2.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-Japan1-3.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-Japan1-3.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-Japan1-4.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-Japan1-4.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-Japan1-5.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-Japan1-5.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-Japan1-6.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-Japan1-6.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-Japan1-UCS2.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-Japan1-UCS2.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-Korea1-0.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-Korea1-0.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-Korea1-1.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-Korea1-1.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-Korea1-2.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-Korea1-2.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Adobe-Korea1-UCS2.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Adobe-Korea1-UCS2.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/B5-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/B5-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/B5-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/B5-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/B5pc-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/B5pc-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/B5pc-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/B5pc-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/CNS-EUC-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/CNS-EUC-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/CNS-EUC-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/CNS-EUC-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/CNS1-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/CNS1-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/CNS1-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/CNS1-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/CNS2-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/CNS2-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/CNS2-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/CNS2-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/ETHK-B5-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/ETHK-B5-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/ETHK-B5-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/ETHK-B5-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/ETen-B5-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/ETen-B5-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/ETen-B5-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/ETen-B5-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/ETenms-B5-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/ETenms-B5-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/ETenms-B5-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/ETenms-B5-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/EUC-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/EUC-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/EUC-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/EUC-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Ext-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Ext-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Ext-RKSJ-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Ext-RKSJ-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Ext-RKSJ-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Ext-RKSJ-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Ext-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Ext-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/GB-EUC-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/GB-EUC-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/GB-EUC-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/GB-EUC-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/GB-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/GB-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/GB-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/GB-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/GBK-EUC-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/GBK-EUC-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/GBK-EUC-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/GBK-EUC-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/GBK2K-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/GBK2K-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/GBK2K-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/GBK2K-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/GBKp-EUC-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/GBKp-EUC-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/GBKp-EUC-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/GBKp-EUC-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/GBT-EUC-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/GBT-EUC-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/GBT-EUC-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/GBT-EUC-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/GBT-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/GBT-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/GBT-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/GBT-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/GBTpc-EUC-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/GBTpc-EUC-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/GBTpc-EUC-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/GBTpc-EUC-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/GBpc-EUC-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/GBpc-EUC-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/GBpc-EUC-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/GBpc-EUC-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/HKdla-B5-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/HKdla-B5-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/HKdla-B5-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/HKdla-B5-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/HKdlb-B5-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/HKdlb-B5-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/HKdlb-B5-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/HKdlb-B5-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/HKgccs-B5-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/HKgccs-B5-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/HKgccs-B5-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/HKgccs-B5-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/HKm314-B5-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/HKm314-B5-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/HKm314-B5-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/HKm314-B5-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/HKm471-B5-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/HKm471-B5-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/HKm471-B5-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/HKm471-B5-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/HKscs-B5-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/HKscs-B5-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/HKscs-B5-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/HKscs-B5-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Hankaku.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Hankaku.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Hiragana.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Hiragana.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/KSC-EUC-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/KSC-EUC-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/KSC-EUC-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/KSC-EUC-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/KSC-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/KSC-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/KSC-Johab-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/KSC-Johab-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/KSC-Johab-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/KSC-Johab-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/KSC-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/KSC-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/KSCms-UHC-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/KSCms-UHC-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/KSCms-UHC-HW-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/KSCms-UHC-HW-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/KSCms-UHC-HW-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/KSCms-UHC-HW-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/KSCms-UHC-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/KSCms-UHC-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/KSCpc-EUC-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/KSCpc-EUC-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/KSCpc-EUC-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/KSCpc-EUC-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Katakana.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Katakana.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/LICENSE": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/LICENSE",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/NWP-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/NWP-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/NWP-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/NWP-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/RKSJ-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/RKSJ-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/RKSJ-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/RKSJ-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/Roman.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/Roman.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniCNS-UCS2-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniCNS-UCS2-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniCNS-UCS2-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniCNS-UCS2-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniCNS-UTF16-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniCNS-UTF16-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniCNS-UTF16-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniCNS-UTF16-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniCNS-UTF32-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniCNS-UTF32-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniCNS-UTF32-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniCNS-UTF32-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniCNS-UTF8-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniCNS-UTF8-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniCNS-UTF8-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniCNS-UTF8-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniGB-UCS2-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniGB-UCS2-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniGB-UCS2-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniGB-UCS2-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniGB-UTF16-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniGB-UTF16-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniGB-UTF16-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniGB-UTF16-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniGB-UTF32-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniGB-UTF32-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniGB-UTF32-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniGB-UTF32-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniGB-UTF8-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniGB-UTF8-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniGB-UTF8-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniGB-UTF8-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniJIS-UCS2-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniJIS-UCS2-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniJIS-UCS2-HW-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniJIS-UCS2-HW-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniJIS-UCS2-HW-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniJIS-UCS2-HW-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniJIS-UCS2-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniJIS-UCS2-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniJIS-UTF16-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniJIS-UTF16-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniJIS-UTF16-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniJIS-UTF16-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniJIS-UTF32-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniJIS-UTF32-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniJIS-UTF32-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniJIS-UTF32-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniJIS-UTF8-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniJIS-UTF8-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniJIS-UTF8-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniJIS-UTF8-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniJIS2004-UTF16-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniJIS2004-UTF16-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniJIS2004-UTF16-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniJIS2004-UTF16-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniJIS2004-UTF32-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniJIS2004-UTF32-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniJIS2004-UTF32-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniJIS2004-UTF32-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniJIS2004-UTF8-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniJIS2004-UTF8-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniJIS2004-UTF8-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniJIS2004-UTF8-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniJISPro-UCS2-HW-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniJISPro-UCS2-HW-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniJISPro-UCS2-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniJISPro-UCS2-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniJISPro-UTF8-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniJISPro-UTF8-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniJISX0213-UTF32-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniJISX0213-UTF32-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniJISX0213-UTF32-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniJISX0213-UTF32-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniJISX02132004-UTF32-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniJISX02132004-UTF32-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniJISX02132004-UTF32-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniJISX02132004-UTF32-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniKS-UCS2-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniKS-UCS2-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniKS-UCS2-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniKS-UCS2-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniKS-UTF16-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniKS-UTF16-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniKS-UTF16-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniKS-UTF16-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniKS-UTF32-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniKS-UTF32-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniKS-UTF32-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniKS-UTF32-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniKS-UTF8-H.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniKS-UTF8-H.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/UniKS-UTF8-V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/UniKS-UTF8-V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/V.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/V.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/cmaps/WP-Symbol.bcmap": {
    "file": "public/vendor/pdfjs-6.2.108/cmaps/WP-Symbol.bcmap",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/package.json": {
    "file": "public/vendor/pdfjs-6.2.108/package.json",
    "contentType": "application/json"
  },
  "/vendor/pdfjs-6.2.108/pdf.mjs": {
    "file": "public/vendor/pdfjs-6.2.108/pdf.mjs",
    "contentType": "text/javascript"
  },
  "/vendor/pdfjs-6.2.108/pdf.worker.mjs": {
    "file": "public/vendor/pdfjs-6.2.108/pdf.worker.mjs",
    "contentType": "text/javascript"
  },
  "/vendor/pdfjs-6.2.108/standard_fonts/FoxitDingbats.pfb": {
    "file": "public/vendor/pdfjs-6.2.108/standard_fonts/FoxitDingbats.pfb",
    "contentType": "application/x-font-type1"
  },
  "/vendor/pdfjs-6.2.108/standard_fonts/FoxitFixed.pfb": {
    "file": "public/vendor/pdfjs-6.2.108/standard_fonts/FoxitFixed.pfb",
    "contentType": "application/x-font-type1"
  },
  "/vendor/pdfjs-6.2.108/standard_fonts/FoxitFixedBold.pfb": {
    "file": "public/vendor/pdfjs-6.2.108/standard_fonts/FoxitFixedBold.pfb",
    "contentType": "application/x-font-type1"
  },
  "/vendor/pdfjs-6.2.108/standard_fonts/FoxitFixedBoldItalic.pfb": {
    "file": "public/vendor/pdfjs-6.2.108/standard_fonts/FoxitFixedBoldItalic.pfb",
    "contentType": "application/x-font-type1"
  },
  "/vendor/pdfjs-6.2.108/standard_fonts/FoxitFixedItalic.pfb": {
    "file": "public/vendor/pdfjs-6.2.108/standard_fonts/FoxitFixedItalic.pfb",
    "contentType": "application/x-font-type1"
  },
  "/vendor/pdfjs-6.2.108/standard_fonts/FoxitSerif.pfb": {
    "file": "public/vendor/pdfjs-6.2.108/standard_fonts/FoxitSerif.pfb",
    "contentType": "application/x-font-type1"
  },
  "/vendor/pdfjs-6.2.108/standard_fonts/FoxitSerifBold.pfb": {
    "file": "public/vendor/pdfjs-6.2.108/standard_fonts/FoxitSerifBold.pfb",
    "contentType": "application/x-font-type1"
  },
  "/vendor/pdfjs-6.2.108/standard_fonts/FoxitSerifBoldItalic.pfb": {
    "file": "public/vendor/pdfjs-6.2.108/standard_fonts/FoxitSerifBoldItalic.pfb",
    "contentType": "application/x-font-type1"
  },
  "/vendor/pdfjs-6.2.108/standard_fonts/FoxitSerifItalic.pfb": {
    "file": "public/vendor/pdfjs-6.2.108/standard_fonts/FoxitSerifItalic.pfb",
    "contentType": "application/x-font-type1"
  },
  "/vendor/pdfjs-6.2.108/standard_fonts/FoxitSymbol.pfb": {
    "file": "public/vendor/pdfjs-6.2.108/standard_fonts/FoxitSymbol.pfb",
    "contentType": "application/x-font-type1"
  },
  "/vendor/pdfjs-6.2.108/standard_fonts/LICENSE_FOXIT": {
    "file": "public/vendor/pdfjs-6.2.108/standard_fonts/LICENSE_FOXIT",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/standard_fonts/LICENSE_LIBERATION": {
    "file": "public/vendor/pdfjs-6.2.108/standard_fonts/LICENSE_LIBERATION",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/standard_fonts/LiberationSans-Bold.ttf": {
    "file": "public/vendor/pdfjs-6.2.108/standard_fonts/LiberationSans-Bold.ttf",
    "contentType": "font/ttf"
  },
  "/vendor/pdfjs-6.2.108/standard_fonts/LiberationSans-BoldItalic.ttf": {
    "file": "public/vendor/pdfjs-6.2.108/standard_fonts/LiberationSans-BoldItalic.ttf",
    "contentType": "font/ttf"
  },
  "/vendor/pdfjs-6.2.108/standard_fonts/LiberationSans-Italic.ttf": {
    "file": "public/vendor/pdfjs-6.2.108/standard_fonts/LiberationSans-Italic.ttf",
    "contentType": "font/ttf"
  },
  "/vendor/pdfjs-6.2.108/standard_fonts/LiberationSans-Regular.ttf": {
    "file": "public/vendor/pdfjs-6.2.108/standard_fonts/LiberationSans-Regular.ttf",
    "contentType": "font/ttf"
  },
  "/vendor/pdfjs-6.2.108/wasm/LICENSE_JBIG2": {
    "file": "public/vendor/pdfjs-6.2.108/wasm/LICENSE_JBIG2",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/wasm/LICENSE_OPENJPEG": {
    "file": "public/vendor/pdfjs-6.2.108/wasm/LICENSE_OPENJPEG",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/wasm/LICENSE_PDFJS_JBIG2": {
    "file": "public/vendor/pdfjs-6.2.108/wasm/LICENSE_PDFJS_JBIG2",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/wasm/LICENSE_PDFJS_OPENJPEG": {
    "file": "public/vendor/pdfjs-6.2.108/wasm/LICENSE_PDFJS_OPENJPEG",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/wasm/LICENSE_PDFJS_QCMS": {
    "file": "public/vendor/pdfjs-6.2.108/wasm/LICENSE_PDFJS_QCMS",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/wasm/LICENSE_QCMS": {
    "file": "public/vendor/pdfjs-6.2.108/wasm/LICENSE_QCMS",
    "contentType": "application/octet-stream"
  },
  "/vendor/pdfjs-6.2.108/wasm/jbig2.wasm": {
    "file": "public/vendor/pdfjs-6.2.108/wasm/jbig2.wasm",
    "contentType": "application/wasm"
  },
  "/vendor/pdfjs-6.2.108/wasm/jbig2_nowasm_fallback.js": {
    "file": "public/vendor/pdfjs-6.2.108/wasm/jbig2_nowasm_fallback.js",
    "contentType": "text/javascript"
  },
  "/vendor/pdfjs-6.2.108/wasm/openjpeg.wasm": {
    "file": "public/vendor/pdfjs-6.2.108/wasm/openjpeg.wasm",
    "contentType": "application/wasm"
  },
  "/vendor/pdfjs-6.2.108/wasm/openjpeg_nowasm_fallback.js": {
    "file": "public/vendor/pdfjs-6.2.108/wasm/openjpeg_nowasm_fallback.js",
    "contentType": "text/javascript"
  },
  "/vendor/pdfjs-6.2.108/wasm/qcms_bg.wasm": {
    "file": "public/vendor/pdfjs-6.2.108/wasm/qcms_bg.wasm",
    "contentType": "application/wasm"
  },
  "/": {
    "file": "public/index.html",
    "contentType": "text/html"
  }
});
/** Resolve only the three packaged renderer assets; no URL-controlled path joins occur. */
export function resolveStaticAsset(requestUrl, rendererRoot) {
    if (!isAbsolute(rendererRoot)) {
        throw new Error("Packaged renderer root must be absolute");
    }
    let parsed;
    try {
        parsed = new URL(requestUrl);
    }
    catch {
        return null;
    }
    if (parsed.protocol !== "app:" ||
        parsed.hostname !== "cosmas" ||
        parsed.port !== "" ||
        parsed.username !== "" ||
        parsed.password !== "" ||
        parsed.search !== "" ||
        parsed.hash !== "") {
        return null;
    }
    const asset = RENDERER_ASSETS[parsed.pathname];
    if (asset === undefined) {
        return null;
    }
    const path = resolve(rendererRoot, asset.file);
    const rootPrefix = rendererRoot.endsWith(sep) ? rendererRoot : `${rendererRoot}${sep}`;
    if (!path.startsWith(rootPrefix)) {
        throw new Error("Packaged renderer asset escaped its root");
    }
    return Object.freeze({ path, contentType: asset.contentType });
}
