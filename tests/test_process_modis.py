"""Unit-тесты для process_modis."""

import numpy as np
import pytest

from process_modis import (
    derive_code,
    grid_lookup_vectorized,
    parse_tile_id,
    tile_to_sinusoidal_bounds,
    CELL_SIZE,
    TILE_SIZE,
    UPPER_LEFT_X,
    UPPER_LEFT_Y,
)


class TestParseTileId:
    def test_standard_name(self):
        assert parse_tile_id("MOD10A1F.A2025335.h23v04.061.hdf") == (23, 4)

    def test_double_digit_v(self):
        assert parse_tile_id("MOD10A1F.A2025001.h10v12.061.hdf") == (10, 12)

    def test_path_with_directory(self):
        assert parse_tile_id("/data/2025-12-01/MOD10A1F.A2025335.h05v05.061.abc.hdf") == (5, 5)


class TestDeriveCode:
    def test_simple(self):
        assert derive_code("Chirchik") == "chirchik"

    def test_with_spaces(self):
        assert derive_code("Piskem Mullala") == "piskem_mullala"

    def test_already_lower(self):
        assert derive_code("ahangaran_irtash") == "ahangaran_irtash"


class TestTileToSinusoidalBounds:
    def test_origin_tile(self):
        x_min, y_min, x_max, y_max = tile_to_sinusoidal_bounds(0, 0)
        tile_width = TILE_SIZE * CELL_SIZE
        assert x_min == pytest.approx(UPPER_LEFT_X)
        assert y_max == pytest.approx(UPPER_LEFT_Y)
        assert x_max == pytest.approx(UPPER_LEFT_X + tile_width)
        assert y_min == pytest.approx(UPPER_LEFT_Y - tile_width)

    def test_tile_size_consistency(self):
        x_min1, _, x_max1, _ = tile_to_sinusoidal_bounds(5, 3)
        x_min2, _, _, _ = tile_to_sinusoidal_bounds(6, 3)
        assert x_max1 == pytest.approx(x_min2)


class TestGridLookupVectorized:
    def test_basic_lookup(self):
        data = np.array([[10, 20], [30, 40]])
        nrows, ncols = 2, 2
        xll, yll, cellsize, nodata = 0.0, 0.0, 1.0, -9999.0

        lons = np.array([0.5, 1.5])
        lats = np.array([1.5, 0.5])
        result = grid_lookup_vectorized(lons, lats, data, xll, yll, cellsize, ncols, nrows, nodata)
        assert result[0] == 10
        assert result[1] == 40

    def test_out_of_bounds(self):
        data = np.array([[1, 2], [3, 4]])
        nodata = -9999.0
        result = grid_lookup_vectorized(
            np.array([100.0]), np.array([100.0]),
            data, 0.0, 0.0, 1.0, 2, 2, nodata,
        )
        assert result[0] == nodata
