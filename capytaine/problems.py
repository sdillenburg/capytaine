#!/usr/bin/env python
# coding: utf-8
"""Definition of the problems to solve with the BEM solver."""
# This file is part of "Capytaine" (https://github.com/mancellin/capytaine).
# It has been written by Matthieu Ancellin and is released under the terms of the GPLv3 license.

import logging
from itertools import product
from functools import lru_cache

from attr import attrs, attrib, astuple

import numpy as np
from scipy.optimize import newton

from capytaine.bodies import FloatingBody
from capytaine.tools.Airy_wave import Airy_wave_velocity


LOG = logging.getLogger(__name__)


@attrs(cmp=False)
class LinearPotentialFlowProblem:
    """General class of a potential flow problem.

    Stores:
    * the environmental variables (gravity and fluid density),
    * the shape of the domain (position of the free surface and of the sea bottom),
    * the frequency of interest,
    * the meshed floating body,
    * the Neumann boundary conditions on the body.
    """
    default_parameters = {'rho': 1000, 'g': 9.81, 'free_surface': 0.0, 'sea_bottom': -np.infty, 'omega': 1.0}

    body = attrib(default=None)
    free_surface = attrib(default=default_parameters['free_surface'])
    sea_bottom = attrib(default=default_parameters['sea_bottom'])
    omega = attrib(default=default_parameters['omega'])
    g = attrib(default=default_parameters['g'])
    rho = attrib(default=default_parameters['rho'])

    @free_surface.validator
    def _check_free_surface(self, _, free_surface):
        if free_surface not in [0, np.infty]:
            raise NotImplementedError(
                "Only z=0 and z=∞ are accepted values for the free surface position at the moment.")
        elif free_surface == np.infty and self.sea_bottom != -np.infty:
            raise NotImplementedError(
                "The case without free surface but with a sea bottom has not been implemented yet.")

    @sea_bottom.validator
    def _check_depth(self, _, sea_bottom):
        if self.free_surface < sea_bottom:
            raise ValueError("Sea bottom is above the free surface.")

    @body.validator
    def _check_body_position(self, _, body):
        if body is not None:
            if (any(body.mesh.faces_centers[:, 2] > self.free_surface)
                    or any(body.mesh.faces_centers[:, 2] < self.sea_bottom)):
                LOG.warning(f"""The mesh of the body {body.name} is not inside the domain.\n
                                Check the values of free_surface and sea_bottom\n
                                or use body.keep_immersed_part() to clip the mesh.""")

    def __str__(self):
        """Do not display default values in str(problem)."""
        parameters = [f"body={self.body.name if self.body is not None else 'None'}",
                      f"omega={self.omega:.3f}",
                      f"depth={self.depth}"]
        try:
            parameters.extend(self._str_other_attributes())
        except AttributeError:
            pass

        if not self.free_surface == self.default_parameters['free_surface']:
            parameters.append(f"free_surface={self.free_surface}")
        if not self.g == self.default_parameters['g']:
            parameters.append(f"g={self.g}")
        if not self.rho == self.default_parameters['rho']:
            parameters.append(f"rho={self.rho}")

        return self.__class__.__name__ + "(" + ', '.join(parameters) + ")"

    def __eq__(self, other):
        if isinstance(other, LinearPotentialFlowProblem):
            return astuple(self)[:6] == astuple(other)[:6]
        else:
            return NotImplemented

    def __lt__(self, other):
        # Arbitrary order. Used for ordering of problems: problems with similar body are grouped together.
        if isinstance(other, LinearPotentialFlowProblem):
            return astuple(self)[:6] < astuple(other)[:6]
        else:
            return NotImplemented

    @property
    def depth(self):
        return self.free_surface - self.sea_bottom

    @property
    # @lru_cache(maxsize=128)
    def wavenumber(self):
        if self.depth == np.infty or self.omega**2*self.depth/self.g > 20:
            return self.omega**2/self.g
        else:
            return newton(lambda x: x*np.tanh(x) - self.omega**2*self.depth/self.g, x0=1.0)/self.depth

    @property
    def wavelength(self):
        return 2*np.pi/self.wavenumber

    @property
    def period(self):
        return 2*np.pi/self.omega

    @property
    def dimensionless_omega(self):
        if self.depth != np.infty:
            return self.omega**2*self.depth/self.g
        else:
            raise AttributeError("Dimensionless omega is defined only for finite depth problems.")

    @property
    def dimensionless_wavenumber(self):
        if self.depth != np.infty:
            return self.wavenumber*self.depth
        else:
            raise AttributeError("Dimensionless wavenumber is defined only for finite depth problems.")

    @property
    def influenced_dofs(self):
        # TODO: let the user choose the influenced dofs
        return self.body.dofs

    def make_results_container(self):
        from capytaine.results import LinearPotentialFlowResult
        return LinearPotentialFlowResult(self)


@attrs(cmp=False)
class DiffractionProblem(LinearPotentialFlowProblem):
    """Particular LinearPotentialFlowProblem whose boundary conditions have
    been computed from an incoming Airy wave."""

    angle = attrib(default=0.0)  # Angle of the incoming wave.
    convention = attrib(default="Nemoh", repr=False)

    def __attrs_post_init__(self):
        if self.body is not None:
            self.boundary_condition = -(
                Airy_wave_velocity(self.body.mesh.faces_centers, self, convention=self.convention)
                * self.body.mesh.faces_normals
            ).sum(axis=1)

    def _str_other_attributes(self):
        return [f"angle={self.angle}"]

    def make_results_container(self):
        from capytaine.results import DiffractionResult
        return DiffractionResult(self)


@attrs(cmp=False)
class RadiationProblem(LinearPotentialFlowProblem):
    """Particular LinearPotentialFlowProblem whose boundary conditions have
    been computed from the degree of freedom of the body."""

    radiating_dof = attrib(default=None)

    def __str__(self):
        """Do not display default values in str(problem)."""
        parameters = [f"body={self.body.name if self.body is not None else 'None'}, "
                      f"omega={self.omega:.3f}, depth={self.depth}, radiating_dof={self.radiating_dof}, "]
        if not self.free_surface == 0.0:
            parameters.append(f"free_surface={self.free_surface}, ")
        if not self.g == 9.81:
            parameters.append(f"g={self.g}, ")
        if not self.rho == 1000:
            parameters.append(f"rho={self.rho}, ")
        return "RadiationProblem(" + ''.join(parameters)[:-2] + ")"

    def __attrs_post_init__(self):
        """Set the boundary condition"""
        if self.body is None:
            self.boundary_condition = None
            return

        if len(self.body.dofs) == 0:
            raise ValueError(f"Body {self.body.name} does not have any degrees of freedom.")

        if self.radiating_dof is None:
            self.radiating_dof = next(iter(self.body.dofs))

        if self.radiating_dof not in self.body.dofs:
            LOG.error(f"In {self}: the radiating degree of freedom {self.radiating_dof} is not one of"
                      f"the degrees of freedom of the body.\n"
                      f"The dofs of the body are {list(self.body.dofs.keys())}")
            raise ValueError("Unrecognized degree of freedom name.")

        dof = self.body.dofs[self.radiating_dof]
        self.boundary_condition = np.sum(dof * self.body.mesh.faces_normals, axis=1)

    def _str_other_attributes(self):
        return [f"radiating_dof={self.radiating_dof}"]

    def make_results_container(self):
        from capytaine.results import RadiationResult
        return RadiationResult(self)


def problems_from_dataset(dataset, bodies):
    """Generate a list of problems from the coordinates of a dataset.

    Parameters
    ----------
    dataset : xarray Dataset
        dataset containing the problems parameters: frequency, radiating_dof, water_depth, ...
    bodies : list of FloatingBody
        the bodies involved in the problems

    Returns
    -------
    list of LinearPotentialFlowProblem
    """
    assert len(list(set(body.name for body in bodies))) == len(bodies), \
        "All bodies should have different names."

    omega_range = dataset['omega'].data if 'omega' in dataset else [1.0]
    angle_range = dataset['angle'].data if 'angle' in dataset else None
    radiating_dofs = dataset['radiating_dof'].data if 'radiating_dof' in dataset else None
    water_depth_range = dataset['water_depth'].data if 'water_depth' in dataset else [np.infty]

    if 'body_name' in dataset:
        assert set(dataset['body_name'].data) <= {body.name for body in bodies}
        body_range = {body.name: body for body in bodies if body.name in dataset['body_name'].data}
    else:
        body_range = {body.name: body for body in bodies}

    problems = []
    if angle_range is not None:
        for omega, angle, water_depth, body_name \
                in product(omega_range, angle_range, water_depth_range, body_range):
            problems.append(
                DiffractionProblem(body=body_range[body_name], omega=omega,
                                   angle=angle, sea_bottom=-water_depth)
            )

    if radiating_dofs is not None:
        for omega, radiating_dof, water_depth, body_name \
                in product(omega_range, radiating_dofs, water_depth_range, body_range):
            problems.append(
                RadiationProblem(body=body_range[body_name], omega=omega,
                                 radiating_dof=radiating_dof, sea_bottom=-water_depth)
            )

    return sorted(problems)
