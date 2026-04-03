"""
CloudProbabilityAPI
Estimates historical cloud coverage probability for a geographic region
using Google Earth Engine's COPERNICUS/S2_CLOUD_PROBABILITY dataset.
"""

from __future__ import annotations

from datetime import datetime

import ee


class CloudProbabilityAPI:
    """
    Estimates cloud coverage probability for a given date and region
    using multi-year Sentinel-2 cloud probability data.

    Args:
        region: ee.Geometry defining the area of interest.
        start_year: First year of the historical range (inclusive).
        end_year: Last year of the historical range (inclusive).
    """

    DATASET = "COPERNICUS/S2_CLOUD_PROBABILITY"
    CLOUD_BAND = "probability"
    CLOUD_THRESHOLD = 60  # pixel considered cloudy if probability > this value
    DEFAULT_SCALE = 100   # metres; coarser than native but fast for statistics

    def __init__(
        self,
        region: ee.Geometry,
        start_year: int = 2019,
        end_year: int = 2024,
    ) -> None:
        self.region = region
        self.start_year = start_year
        self.end_year = end_year
        self.collection = self._load_collection()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_collection(self) -> ee.ImageCollection:
        """Load the cloud-probability collection filtered to region and years."""
        return (
            ee.ImageCollection(self.DATASET)
            .filterBounds(self.region)
            .filter(
                ee.Filter.calendarRange(self.start_year, self.end_year, "year")
            )
        )

    def _filter_by_date_window(
        self, target_date: datetime, window_days: int
    ) -> ee.ImageCollection:
        """
        Filter collection to images whose day-of-year falls within
        [doy - window_days, doy + window_days], handling year-boundary wrap.
        """
        doy = target_date.timetuple().tm_yday
        start_doy = doy - window_days
        end_doy = doy + window_days

        if start_doy < 1 and end_doy > 365:
            # Window spans the entire year — no filtering needed
            doy_filter = ee.Filter.calendarRange(1, 365, "day_of_year")
        elif start_doy < 1:
            # Wraps around the start of the year
            doy_filter = ee.Filter.Or(
                ee.Filter.calendarRange(start_doy + 365, 365, "day_of_year"),
                ee.Filter.calendarRange(1, end_doy, "day_of_year"),
            )
        elif end_doy > 365:
            # Wraps around the end of the year
            doy_filter = ee.Filter.Or(
                ee.Filter.calendarRange(start_doy, 365, "day_of_year"),
                ee.Filter.calendarRange(1, end_doy - 365, "day_of_year"),
            )
        else:
            doy_filter = ee.Filter.calendarRange(start_doy, end_doy, "day_of_year")

        return self.collection.filter(doy_filter)

    def _compute_cloud_percentage(self, image: ee.Image) -> ee.Image:
        """
        Compute the percentage of cloudy pixels in the region for one image.
        A pixel is cloudy when its probability value exceeds CLOUD_THRESHOLD.
        Result is stored as the 'cloud_percentage' image property.
        """
        cloud_mask = image.select(self.CLOUD_BAND).gt(self.CLOUD_THRESHOLD).unmask(0)
        stats = cloud_mask.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=self.region,
            scale=self.DEFAULT_SCALE,
            maxPixels=1e9,
        )
        # reduceRegion can return null when the image footprint doesn't fully
        # cover the region. ee.Algorithms.If handles this server-side:
        # null and 0 are both falsy in GEE, so a 0% result stays 0.
        value = stats.get(self.CLOUD_BAND)
        cloud_pct = ee.Number(
            ee.Algorithms.If(value, ee.Number(value).multiply(100), 0)
        )
        return image.set("cloud_percentage", cloud_pct)

    def _collection_with_cloud_pct(
        self, target_date: datetime, window_days: int
    ) -> ee.ImageCollection:
        """Return the date-windowed collection with 'cloud_percentage' attached."""
        filtered = self._filter_by_date_window(target_date, window_days)
        return filtered.map(self._compute_cloud_percentage)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_cloud_probability(
        self, target_date: datetime, window_days: int = 15
    ) -> dict[str, float]:
        """
        Estimate cloud coverage probability for a target date.

        Collects historical images within ±window_days of the target day-of-year
        across all years in [start_year, end_year] and computes aggregate statistics.

        Args:
            target_date: The date of interest.
            window_days: Half-width of the day-of-year window.

        Returns:
            {"mean": float, "std": float}  — cloud coverage percentage (0–100).
        """
        with_pct = self._collection_with_cloud_pct(target_date, window_days)

        # Convert to FeatureCollection so reduceColumns can aggregate the scalar property
        fc = ee.FeatureCollection(
            with_pct.map(
                lambda img: ee.Feature(
                    None, {"cloud_percentage": img.get("cloud_percentage")}
                )
            )
        )

        stats = fc.reduceColumns(
            reducer=ee.Reducer.mean().combine(
                ee.Reducer.stdDev(), sharedInputs=True
            ),
            selectors=["cloud_percentage"],
        ).getInfo()

        return {
            "mean": stats.get("mean", 0.0),
            "std": stats.get("stdDev", 0.0),
        }

    def get_similar_images(
        self, target_date: datetime, n: int = 5, window_days: int = 15
    ) -> list[dict]:
        """
        Retrieve the N historical images whose cloud coverage is closest
        to the expected (mean) value for the target date.

        Args:
            target_date: The date of interest.
            n: Number of images to return.
            window_days: Half-width of the day-of-year window.

        Returns:
            List of image info dicts sorted by proximity to expected cloud coverage.
            Each dict includes standard GEE metadata plus 'cloud_percentage'.
        """
        prob = self.get_cloud_probability(target_date, window_days)
        expected = prob["mean"]

        with_pct = self._collection_with_cloud_pct(target_date, window_days)

        with_distance = with_pct.map(
            lambda img: img.set(
                "distance_to_expected",
                ee.Number(img.get("cloud_percentage")).subtract(expected).abs(),
            )
        )

        top_n = with_distance.sort("distance_to_expected").limit(n)
        return top_n.getInfo()["features"]

    # ------------------------------------------------------------------
    # Bonus: visualisation
    # ------------------------------------------------------------------

    def visualize(
        self,
        target_date: datetime,
        n: int = 1,
        window_days: int = 15,
    ):
        """
        Display the most representative image(s) on an interactive geemap map.

        Requires geemap and a Jupyter / Colab environment.
        """
        try:
            import geemap
        except ImportError as exc:
            raise ImportError(
                "geemap is required for visualisation. "
                "Install it with: pip install geemap"
            ) from exc

        images = self.get_similar_images(target_date, n=n, window_days=window_days)
        m = geemap.Map()
        m.centerObject(self.region, zoom=10)

        vis_params = {"min": 0, "max": 100, "palette": ["green", "yellow", "red"]}

        for feature in images:
            img_id = feature["id"]
            img = ee.Image(img_id).select(self.CLOUD_BAND)
            cloud_pct = feature["properties"].get("cloud_percentage", float("nan"))
            label = f"{img_id.split('/')[-1]}  ({cloud_pct:.1f}% cloud)"
            m.addLayer(img, vis_params, label)

        m.addLayer(self.region, {}, "Region of Interest")
        return m

    def plot_time_series(
        self,
        target_date: datetime,
        window_days: int = 15,
    ) -> None:
        """
        Plot cloud coverage percentage over time for the filtered collection.

        Requires matplotlib and a Jupyter / Colab environment.
        """
        try:
            import matplotlib.pyplot as plt
        except ImportError as exc:
            raise ImportError(
                "matplotlib is required for plotting. "
                "Install it with: pip install matplotlib"
            ) from exc

        with_pct = self._collection_with_cloud_pct(target_date, window_days)

        fc = ee.FeatureCollection(
            with_pct.map(
                lambda img: ee.Feature(
                    None,
                    {
                        "date": img.date().format("YYYY-MM-dd"),
                        "cloud_percentage": img.get("cloud_percentage"),
                    },
                )
            )
        )
        records = sorted(
            fc.getInfo()["features"],
            key=lambda f: f["properties"]["date"],
        )

        dates = [f["properties"]["date"] for f in records]
        values = [f["properties"]["cloud_percentage"] for f in records]
        prob = self.get_cloud_probability(target_date, window_days)
        mean, std = prob["mean"], prob["std"]

        fig, ax = plt.subplots(figsize=(12, 4))
        ax.plot(dates, values, marker="o", linewidth=1, markersize=4, label="Cloud %")
        ax.axhline(mean, color="red", linestyle="--", label=f"Mean = {mean:.1f}%")
        ax.fill_between(
            range(len(dates)),
            mean - std,
            mean + std,
            alpha=0.15,
            color="red",
            label=f"±1 std ({std:.1f}%)",
        )
        ax.set_title(
            f"Cloud coverage — {target_date.strftime('%b %d')} ± {window_days} days"
            f"  ({self.start_year}–{self.end_year})"
        )
        ax.set_xlabel("Date")
        ax.set_ylabel("Cloud coverage (%)")
        step = max(1, len(dates) // 10)
        ax.set_xticks(range(0, len(dates), step))
        ax.set_xticklabels(dates[::step], rotation=45, ha="right")
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.show()
