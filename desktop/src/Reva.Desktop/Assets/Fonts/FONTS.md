# Bundled fonts

IBM Plex Sans (Regular, Medium, SemiBold) and IBM Plex Mono (Regular, Medium), bundled locally so the
app looks the same on every PC and never fetches fonts from the network. Licence: SIL Open Font
License 1.1 (`OFL-IBM-Plex.txt`).

| File | SHA-256 | Source |
|---|---|---|
| IBMPlexSans-Regular.ttf | 975dcda37d80f038dcd143c22e33ca2d97a0cc5a929aace1c749153b0fe1afa5 | github.com/IBM/plex release `@ibm/plex-sans@1.1.0`, fonts/complete/ttf |
| IBMPlexSans-Medium.ttf | 331c8639d7598b2cde62a911a71db195e30cb655cd6bdf2e324a7e984955f907 | same |
| IBMPlexSans-SemiBold.ttf | a20caf8286023a6a7a85e40b1d2a4ae9fc3e3b1f9eda8f4c542dd4986af67bb1 | same |
| IBMPlexMono-Regular.ttf | 6a3412f058c7d8dfd9170c41e85ade48e5156ecb89356110ca57a0a27734af46 | github.com/google/fonts, ofl/ibmplexmono |
| IBMPlexMono-Medium.ttf | a9b4c49bb299e05b5f6c481e7fb5e78943d2793249a0c8874ab574a2d1ea6755 | same |

Numbers (balances, amounts, ids) use Plex Mono; everything else uses Plex Sans.

Note: IBM's Medium and SemiBold Sans files register the family names `IBM Plex Sans Medm` and
`IBM Plex Sans SmBld` (name ID 1), and that is what the `ms-appx:///...#family` references in
`Themes/RevaTheme.xaml` must use.
