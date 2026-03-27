#include "selective_route_exchange.h"

#include <pybind11/pybind11.h>

namespace py = pybind11;

PYBIND11_MODULE(_srex_plugin, m)
{
    m.def("selective_route_exchange_candidate",
          &pyvrp::crossover::selectiveRouteExchange,
          py::arg("parents"),
          py::arg("data"),
          py::arg("cost_evaluator"),
          py::arg("start_indices"),
          py::arg("num_moved_routes"),
          py::call_guard<py::gil_scoped_release>());
}
