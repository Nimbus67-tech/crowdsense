from crowdsense.geometry import point_in_polygon, polygon_area, segments_intersect

SQUARE = [(0, 0), (10, 0), (10, 10), (0, 10)]


def test_point_in_polygon():
    assert point_in_polygon((5, 5), SQUARE)
    assert not point_in_polygon((15, 5), SQUARE)
    assert not point_in_polygon((5, -1), SQUARE)


def test_concave_polygon():
    L = [(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)]
    assert point_in_polygon((2, 8), L)
    assert not point_in_polygon((8, 8), L)  # in the notch of the L


def test_area():
    assert polygon_area(SQUARE) == 100


def test_segments_cross_and_miss():
    assert segments_intersect((5, -5), (5, 5), (0, 0), (10, 0))
    assert not segments_intersect((5, 1), (5, 5), (0, 0), (10, 0))  # never reaches the line
    assert not segments_intersect((15, -5), (15, 5), (0, 0), (10, 0))  # passes beside the line segment


def test_standing_on_the_line_is_not_double_counted():
    # Walk from below, land exactly on the line, then continue above: exactly one crossing in total.
    line = ((0, 0), (10, 0))
    crossings = sum(
        segments_intersect(a, b, *line) for a, b in [((5, -3), (5, 0)), ((5, 0), (5, 3))]
    )
    assert crossings == 1
