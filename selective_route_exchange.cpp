#include "selective_route_exchange.h"

#include "DynamicBitset.h"

#include <cmath>
#include <vector>

using Client = size_t;
using Clients = std::vector<Client>;
using Route = pyvrp::Route;
using Routes = std::vector<Route>;

namespace
{
// Angle of the given route w.r.t. the centroid of all client locations.
double routeAngle(pyvrp::ProblemData const &data, Route const &route)
{
    auto const [dataX, dataY] = data.centroid();
    auto const [routeX, routeY] = route.centroid();
    return std::atan2((routeY - dataY).get(), (routeX - dataX).get());
}

Routes sortByAscAngle(pyvrp::ProblemData const &data, Routes routes)
{
    auto cmp = [&data](Route const &a, Route const &b)
    { return routeAngle(data, a) < routeAngle(data, b); };

    std::sort(routes.begin(), routes.end(), cmp);
    return routes;
}
}  // namespace

pyvrp::Solution pyvrp::crossover::selectiveRouteExchange(
    std::pair<Solution const *, Solution const *> const &parents,
    ProblemData const &data,
    CostEvaluator const &costEvaluator,
    std::pair<size_t, size_t> const &startIndices,
    size_t const numMovedRoutes)
{
    // We create two candidate offsprings, both based on parent A:
    // Let A and B denote the set of customers selected from parents A and B
    // Ac and Bc denote the complements: the customers not selected
    // Let v denote union and ^ intersection
    // Parent A: A v Ac
    // Parent B: B v Bc

    // Offspring 1:
    // B and Ac\B, remainder A\B unplanned
    // (note B v (Ac\B) v (A\B) = B v ((Ac v A)\B) = B v Bc = all)
    // Note Ac\B = (A v B)c

    // Offspring 2:
    // A^B and Ac, remainder A\B unplanned
    // (note A^B v Ac v A\B = (A^B v A\B) v Ac = A v Ac = all)

    auto startA = startIndices.first;
    auto startB = startIndices.second;

    size_t nRoutesA = parents.first->numRoutes();
    size_t nRoutesB = parents.second->numRoutes();

    if (startA >= nRoutesA)
        throw std::invalid_argument("Expected startA < nRoutesA.");

    if (startB >= nRoutesB)
        throw std::invalid_argument("Expected startB < nRoutesB.");

    if (numMovedRoutes < 1 || numMovedRoutes > std::min(nRoutesA, nRoutesB))
    {
        auto msg = "Expected numMovedRoutes in [1, min(nRoutesA, nRoutesB)]";
        throw std::invalid_argument(msg);
    }

    // Sort parents' routes by (ascending) polar angle.
    auto const routesA = sortByAscAngle(data, parents.first->routes());
    auto const routesB = sortByAscAngle(data, parents.second->routes());

    DynamicBitset selectedA(data.numLocations());
    DynamicBitset selectedB(data.numLocations());

    // Routes are sorted on polar angle, so selecting adjacent routes in both
    // parents should result in a large overlap when the start indices are
    // close to each other.
    for (size_t r = 0; r < numMovedRoutes; r++)
    {
        for (Client c : routesA[(startA + r) % nRoutesA])
            selectedA[c] = true;

        for (Client c : routesB[(startB + r) % nRoutesB])
            selectedB[c] = true;
    }

    // Optimize route selection by aligning routes with similar angular orientation
    // This ensures better spatial coherence, leading to a better structural
    // integrity and potentially lower penalized cost.
    auto routeAnglesA = std::vector<double>(nRoutesA);
    auto routeAnglesB = std::vector<double>(nRoutesB);

    for (size_t i = 0; i < nRoutesA; ++i)
    {
        routeAnglesA[i] = routeAngle(data, routesA[i]);
    }

    for (size_t i = 0; i < nRoutesB; ++i)
    {
        routeAnglesB[i] = routeAngle(data, routesB[i]);
    }

    // Compute initial angular deviation
    double currentAngularDeviation = 0.0;
    for (size_t i = 0; i < numMovedRoutes; ++i)
    {
        size_t idxA = (startA + i) % nRoutesA;
        size_t idxB = (startB + i) % nRoutesB;
        currentAngularDeviation += std::abs(routeAnglesA[idxA] - routeAnglesB[idxB]);
    }

    // MODIFY: Expand the search space for minimal angular deviation to improve
    // spatial coherence and reduce penalized cost
    for (int shiftA = -3; shiftA <= 3; ++shiftA)
    {
        for (int shiftB = -3; shiftB <= 3; ++shiftB)
        {
            size_t newStartA = (startA + shiftA + nRoutesA) % nRoutesA;
            size_t newStartB = (startB + shiftB + nRoutesB) % nRoutesB;
            double newAngularDeviation = 0.0;

            for (size_t i = 0; i < numMovedRoutes; ++i)
            {
                size_t idxA = (newStartA + i) % nRoutesA;
                size_t idxB = (newStartB + i) % nRoutesB;
                newAngularDeviation += std::abs(routeAnglesA[idxA] - routeAnglesB[idxB]);
            }

            if (newAngularDeviation < currentAngularDeviation)
            {
                startA = newStartA;
                startB = newStartB;
                currentAngularDeviation = newAngularDeviation;
            }
        }
    }

    // Re-initialize the bitsets after shifting
    selectedA.reset();
    selectedB.reset();

    for (size_t r = 0; r < numMovedRoutes; r++)
    {
        for (Client c : routesA[(startA + r) % nRoutesA])
            selectedA[c] = true;

        for (Client c : routesB[(startB + r) % nRoutesB])
            selectedB[c] = true;
    }

    // Identify differences between route sets
    auto const selectedBNotA = selectedB & ~selectedA;

    std::vector<Clients> visits1(nRoutesA);
    std::vector<Clients> visits2(nRoutesA);

    // Replace selected routes from parent A with routes from parent B
    for (size_t r = 0; r < numMovedRoutes; r++)
    {
        size_t indexA = (startA + r) % nRoutesA;
        size_t indexB = (startB + r) % nRoutesB;

        for (Client c : routesB[indexB])
        {
            visits1[indexA].push_back(c);  // c in B

            if (!selectedBNotA[c])
                visits2[indexA].push_back(c);  // c in A^B
        }
    }

    // Move routes from parent A that are kept
    for (size_t r = numMovedRoutes; r < nRoutesA; r++)
    {
        size_t indexA = (startA + r) % nRoutesA;

        for (Client c : routesA[indexA])
        {
            if (!selectedBNotA[c])
                visits1[indexA].push_back(c);  // c in Ac\B

            visits2[indexA].push_back(c);  // c in Ac
        }
    }

    // Turn visits back into routes.
    Routes routes1;
    Routes routes2;
    for (size_t r = 0; r < nRoutesA; r++)
    {
        if (!visits1[r].empty())
            routes1.emplace_back(data, visits1[r], routesA[r].vehicleType());

        if (!visits2[r].empty())
            routes2.emplace_back(data, visits2[r], routesA[r].vehicleType());
    }

    auto const sol1 = Solution(data, routes1);
    auto const sol2 = Solution(data, routes2);

    auto const cost1 = costEvaluator.penalisedCost(sol1);
    auto const cost2 = costEvaluator.penalisedCost(sol2);
    return cost1 < cost2 ? sol1 : sol2;
}
