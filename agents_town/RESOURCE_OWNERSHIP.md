# Resource ownership

| Owner | Runtime resources | Consumers |
| --- | --- | --- |
| `interactive` | `resources/scenarios`, `resources/worlds`, `resources/rules`, interactive templates/CSS/JS | Interactive loader and Flask application only |
| `legacy` | prompts, village map/tilemap, replay frontend, character templates | Open-world simulation, launcher, replay, legacy tools and media jobs |
| `common` | character visuals and lore authoring sources | Both applications through explicit common paths |

`results/interactive/` and `results/legacy/` contain runtime output and are not
application resources.  Compatibility readers may inspect the historical
top-level legacy result folders, but new writes must use the namespaced paths.

The dependency direction is `interactive -> common` and `legacy -> common`.
Neither application may import the other, and `common` may not import either.
