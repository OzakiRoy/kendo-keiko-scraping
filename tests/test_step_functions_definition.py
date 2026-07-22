from __future__ import annotations

import json
import unittest
from pathlib import Path


class StepFunctionsDefinitionTests(unittest.TestCase):
    def test_definition_uses_inline_map_and_three_handlers(self) -> None:
        path = Path("infra/step-functions/kendo-keiko-scraper.asl.json")
        definition = json.loads(path.read_text(encoding="utf-8"))

        states = definition["States"]
        self.assertEqual("ListEnabledSources", definition["StartAt"])
        self.assertEqual(2, states["ScrapeSources"]["MaxConcurrency"])
        self.assertEqual(
            "INLINE",
            states["ScrapeSources"]["ItemProcessor"]["ProcessorConfig"][
                "Mode"
            ],
        )
        self.assertEqual(
            "${ListSourcesFunctionArn}",
            states["ListEnabledSources"]["Parameters"]["FunctionName"],
        )
        self.assertEqual(
            "${PublisherFunctionArn}",
            states["PublishPublicSite"]["Parameters"]["FunctionName"],
        )
        worker = states["ScrapeSources"]["ItemProcessor"]["States"][
            "InvokeScraperWorker"
        ]
        self.assertEqual(
            "${ScraperWorkerFunctionArn}",
            worker["Parameters"]["FunctionName"],
        )
        self.assertEqual("BuildFailureResult", worker["Catch"][0]["Next"])


if __name__ == "__main__":
    unittest.main()
