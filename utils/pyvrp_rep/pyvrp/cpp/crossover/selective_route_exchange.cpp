#include "selective_route_exchange.h"

#include "DynamicBitset.h"

#include <algorithm>
#include <cmath>
#include <tuple>
#include <vector>

using Client = size_t;
using Clients = std::vector<Client>;
using DynamicBitset = pyvrp::DynamicBitset;
using Route = pyvrp::Route;
using Routes = std::vector<Route>;

namespace
{
constexpr double PI = 3.14159265358979323846;

double polarAngle(pyvrp::ProblemData const &data, Route const &route)
{
    auto const [dataX, dataY] = data.centroid();
    auto const [routeX, routeY] = route.centroid();
    return std::atan2((routeY - dataY).get(), (routeX - dataX).get());
}

double circularGap(double lhs, double rhs)
{
    auto const diff = std::abs(lhs - rhs);
    return std::min(diff, 2.0 * PI - diff);
}

Routes orderedRoutes(pyvrp::ProblemData const &data, Routes routes)
{
    std::sort(routes.begin(),
              routes.end(),
              [&data](Route const &lhs, Route const &rhs)
              { return polarAngle(data, lhs) < polarAngle(data, rhs); });
    return routes;
}

std::vector<double> routeAngles(pyvrp::ProblemData const &data, Routes const &routes)
{
    std::vector<double> angles;
    angles.reserve(routes.size());

    for (Route const &route : routes)
        angles.push_back(polarAngle(data, route));

    return angles;
}

size_t wrappedIndex(size_t index, int delta, size_t modulus)
{
    auto shifted = static_cast<int>(index) + delta;
    shifted %= static_cast<int>(modulus);

    if (shifted < 0)
        shifted += static_cast<int>(modulus);

    return static_cast<size_t>(shifted);
}

DynamicBitset selectedClients(Routes const &routes,
                              size_t start,
                              size_t numMovedRoutes,
                              size_t numLocations)
{
    DynamicBitset selected(numLocations);

    for (size_t offset = 0; offset != numMovedRoutes; ++offset)
    {
        for (Client client : routes[(start + offset) % routes.size()])
            selected[client] = true;
    }

    return selected;
}

struct WindowScore
{
    size_t replannedClients = 0;
    size_t introducedClients = 0;
    size_t routeSizeMismatch = 0;
    double angularMismatch = 0.0;

    [[nodiscard]] auto asTuple() const
    {
        return std::tuple(replannedClients,
                          introducedClients,
                          routeSizeMismatch,
                          angularMismatch);
    }

    [[nodiscard]] bool operator<(WindowScore const &other) const
    {
        return asTuple() < other.asTuple();
    }
};

WindowScore evaluateWindow(Routes const &routesA,
                           Routes const &routesB,
                           std::vector<double> const &anglesA,
                           std::vector<double> const &anglesB,
                           size_t startA,
                           size_t startB,
                           size_t numMovedRoutes,
                           size_t numLocations)
{
    auto const selectedA = selectedClients(routesA, startA, numMovedRoutes, numLocations);
    auto const selectedB = selectedClients(routesB, startB, numMovedRoutes, numLocations);

    WindowScore score;
    score.replannedClients = (selectedA & ~selectedB).count();
    score.introducedClients = (selectedB & ~selectedA).count();

    for (size_t offset = 0; offset != numMovedRoutes; ++offset)
    {
        auto const idxA = (startA + offset) % routesA.size();
        auto const idxB = (startB + offset) % routesB.size();

        score.routeSizeMismatch += std::abs(
            static_cast<int>(routesA[idxA].size()) - static_cast<int>(routesB[idxB].size()));
        score.angularMismatch += circularGap(anglesA[idxA], anglesB[idxB]);
    }

    return score;
}

std::pair<size_t, size_t> chooseWindow(Routes const &routesA,
                                       Routes const &routesB,
                                       std::vector<double> const &anglesA,
                                       std::vector<double> const &anglesB,
                                       size_t startA,
                                       size_t startB,
                                       size_t numMovedRoutes,
                                       size_t numLocations)
{
    auto bestStartA = startA;
    auto bestStartB = startB;
    auto bestScore = evaluateWindow(routesA,
                                    routesB,
                                    anglesA,
                                    anglesB,
                                    startA,
                                    startB,
                                    numMovedRoutes,
                                    numLocations);

    auto const maxShiftA = static_cast<int>(std::min<size_t>(2, routesA.size() - 1));
    auto const maxShiftB = static_cast<int>(std::min<size_t>(2, routesB.size() - 1));

    for (int deltaA = -maxShiftA; deltaA <= maxShiftA; ++deltaA)
    {
        for (int deltaB = -maxShiftB; deltaB <= maxShiftB; ++deltaB)
        {
            auto const candidateA = wrappedIndex(startA, deltaA, routesA.size());
            auto const candidateB = wrappedIndex(startB, deltaB, routesB.size());

            auto const candidateScore = evaluateWindow(routesA,
                                                       routesB,
                                                       anglesA,
                                                       anglesB,
                                                       candidateA,
                                                       candidateB,
                                                       numMovedRoutes,
                                                       numLocations);

            if (candidateScore < bestScore)
            {
                bestScore = candidateScore;
                bestStartA = candidateA;
                bestStartB = candidateB;
            }
        }
    }

    return {bestStartA, bestStartB};
}

void importMovedRoutes(std::vector<Clients> &offspring1Visits,
                       std::vector<Clients> &offspring2Visits,
                       Routes const &routesB,
                       DynamicBitset const &selectedBNotA,
                       size_t startA,
                       size_t startB,
                       size_t numMovedRoutes,
                       size_t nRoutesA,
                       size_t nRoutesB)
{
    for (size_t offset = 0; offset != numMovedRoutes; ++offset)
    {
        auto const indexA = (startA + offset) % nRoutesA;
        auto const indexB = (startB + offset) % nRoutesB;

        for (Client client : routesB[indexB])
        {
            offspring1Visits[indexA].push_back(client);

            if (!selectedBNotA[client])
                offspring2Visits[indexA].push_back(client);
        }
    }
}

void importKeptRoutes(std::vector<Clients> &offspring1Visits,
                      std::vector<Clients> &offspring2Visits,
                      Routes const &routesA,
                      DynamicBitset const &selectedBNotA,
                      size_t startA,
                      size_t numMovedRoutes,
                      size_t nRoutesA)
{
    for (size_t offset = numMovedRoutes; offset != nRoutesA; ++offset)
    {
        auto const indexA = (startA + offset) % nRoutesA;

        for (Client client : routesA[indexA])
        {
            if (!selectedBNotA[client])
                offspring1Visits[indexA].push_back(client);

            offspring2Visits[indexA].push_back(client);
        }
    }
}

pyvrp::Solution buildOffspring(pyvrp::ProblemData const &data,
                               std::vector<Clients> const &visits,
                               Routes const &referenceRoutes)
{
    Routes offspringRoutes;
    offspringRoutes.reserve(visits.size());

    for (size_t idx = 0; idx != visits.size(); ++idx)
    {
        if (!visits[idx].empty())
            offspringRoutes.emplace_back(data, visits[idx], referenceRoutes[idx].vehicleType());
    }

    return pyvrp::Solution(data, offspringRoutes);
}
}  // namespace

pyvrp::Solution pyvrp::crossover::selectiveRouteExchange(
    std::pair<Solution const *, Solution const *> const &parents,
    ProblemData const &data,
    CostEvaluator const &costEvaluator,
    std::pair<size_t, size_t> const &startIndices,
    size_t const numMovedRoutes)
{
    auto startA = startIndices.first;
    auto startB = startIndices.second;

    auto const nRoutesA = parents.first->numRoutes();
    auto const nRoutesB = parents.second->numRoutes();

    if (startA >= nRoutesA)
        throw std::invalid_argument("Expected startA < nRoutesA.");

    if (startB >= nRoutesB)
        throw std::invalid_argument("Expected startB < nRoutesB.");

    if (numMovedRoutes < 1 || numMovedRoutes > std::min(nRoutesA, nRoutesB))
    {
        auto const msg = "Expected numMovedRoutes in [1, min(nRoutesA, nRoutesB)]";
        throw std::invalid_argument(msg);
    }

    auto const routesA = orderedRoutes(data, parents.first->routes());
    auto const routesB = orderedRoutes(data, parents.second->routes());
    auto const anglesA = routeAngles(data, routesA);
    auto const anglesB = routeAngles(data, routesB);

    // MODIFY: Search a small neighborhood of route windows and prefer the one
    // MODIFY: with the fewest replanned clients, using angle and size as ties.
    auto const [bestStartA, bestStartB] = chooseWindow(routesA,
                                                       routesB,
                                                       anglesA,
                                                       anglesB,
                                                       startA,
                                                       startB,
                                                       numMovedRoutes,
                                                       data.numLocations());
    startA = bestStartA;
    startB = bestStartB;

    auto const selectedA = selectedClients(routesA,
                                           startA,
                                           numMovedRoutes,
                                           data.numLocations());
    auto const selectedB = selectedClients(routesB,
                                           startB,
                                           numMovedRoutes,
                                           data.numLocations());
    auto const selectedBNotA = selectedB & ~selectedA;

    std::vector<Clients> offspring1Visits(nRoutesA);
    std::vector<Clients> offspring2Visits(nRoutesA);

    importMovedRoutes(offspring1Visits,
                      offspring2Visits,
                      routesB,
                      selectedBNotA,
                      startA,
                      startB,
                      numMovedRoutes,
                      nRoutesA,
                      nRoutesB);
    importKeptRoutes(offspring1Visits,
                     offspring2Visits,
                     routesA,
                     selectedBNotA,
                     startA,
                     numMovedRoutes,
                     nRoutesA);

    auto const offspring1 = buildOffspring(data, offspring1Visits, routesA);
    auto const offspring2 = buildOffspring(data, offspring2Visits, routesA);

    auto const cost1 = costEvaluator.penalisedCost(offspring1);
    auto const cost2 = costEvaluator.penalisedCost(offspring2);
    return cost2 < cost1 ? offspring2 : offspring1;
}
