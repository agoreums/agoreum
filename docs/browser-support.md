# Browser support

Agoreum targets the browsers declared in `.hintrc`:

| Engine | Floor | Released |
| --- | --- | --- |
| Chrome / Edge / Chrome Android | 111 | March 2023 |
| Safari / iOS Safari | 16.4 | March 2023 |
| Firefox | 128 | July 2024 |

The floor is not arbitrary. Two things set it.

`color-mix()` in the oklab space carries the whole design system: surface tints,
border strengths, the ambient glows, and the selection colour are all derived
rather than hand-listed, so a single brand token change stays coherent everywhere.
That landed in Chrome 111 and Safari 16.4. Every use is a progressive enhancement,
a browser that does not understand the declaration drops it and falls back to the
underlying colour, so nothing breaks below the floor, it just looks plainer.

The product also requires a wallet. A visitor without a browser wallet or
WalletConnect cannot transact regardless of how the CSS renders, and that
population overlaps almost entirely with browsers older than the floor above.

`text-size-adjust` is exempted in `.hintrc` because the prefixed and unprefixed
forms are both required and neither is dead code: WebKit honours
`-webkit-text-size-adjust`, Chromium implements the standard property. Declaring
one without the other leaves a real gap on one engine or the other, so the
compatibility hint is noise in that specific case.
