# Third-party notices

`backend/wechat_crypto.py` ports the ISAAC64 algorithm in
[`nobiyou/wx_channel`](https://github.com/nobiyou/wx_channel),
`pkg/util/isaac64.go`, commit `1d494115df37320c6bf524baf1977dc669797d5c`.

Copyright (c) 2025 nobiyou. Licensed under the MIT License; the full text is
preserved in [third_party/wx_channel-LICENSE](third_party/wx_channel-LICENSE).

The optional wx_channel companion is a separate application. Its proxy,
certificate management, Windows executables and bundled third-party libraries
are not copied into PIANXI. PIANXI calls its share-resolution API and implements
bounded media download and decoding in Python.
