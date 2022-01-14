from nptyping import NDArray
import gurobipy as gp
import logging


class BinarySolver:
    """
    Solver in the case of two categories.
    Here, the categories are 'Accepted', 'Refused'

    """

    def __init__(
        self, nb_courses: int, nb_students: int, nb_categories: int = 2
    ) -> None:
        """Initialize solver"""

        assert nb_courses >= 1, nb_students >= 1
        assert nb_categories >= 2

        self.h_max = nb_categories - 1
        self.nb_courses = nb_courses
        self.nb_students = nb_students

        self.model = gp.Model("MR sort")

        self.model.setParam(gp.GRB.Param.DualReductions, 0)

        ####################################
        # Problem representation variables #
        ####################################

        # weights of courses
        self.w_i = self.model.addMVar(shape=(nb_courses,), name="w_i")

        # boudaries between validated/non-validated courses
        self.b_i_h = self.model.addMVar(shape=(nb_courses, self.h_max), name="b_i")

        # acceptance criteria
        self.lambda_ = self.model.addVar(name="lambda_")

        self.d_i_j_h = self.model.addMVar(
            shape=(nb_courses, nb_students, self.h_max), vtype=gp.GRB.BINARY
        )

        self.c_i_j_h = self.model.addMVar(
            shape=(nb_courses, nb_students, self.h_max), vtype=gp.GRB.CONTINUOUS
        )
        ###############################
        # Objectif function variables #
        ###############################

        # Alpha is continuous in [0, 1]
        self.alpha = self.model.addVar()
        self.x_j = self.model.addMVar(shape=(nb_students), vtype=gp.GRB.CONTINUOUS)
        self.y_j = self.model.addMVar(shape=(nb_students), vtype=gp.GRB.CONTINUOUS)

        # self.g_j = self.model.addMVar(shape=(nb_students), vtype=gp.GRB.BINARY)
        ####################
        # Useful variables #
        ####################
        self.small = 1e-3
        self.large = 100

        self.model.update()

    def solve(self, accepted_j_i: NDArray[float], refused_j_i: NDArray[float]):
        """Find the right parameters"""
        nb_accepted = len(accepted_j_i)
        nb_refused = len(refused_j_i)

        ######################
        # Global constraints #
        ######################

        # sum of weights should be equal to one
        self.model.addConstr(
            gp.quicksum(self.w_i[i] for i in range(self.nb_courses)) == 1
        )
        self.model.addConstrs(
            self.c_i_j_h[i, j, l] <= self.w_i[i]
            for i in range(self.nb_courses)
            for j in range(self.nb_students)
            for l in range(self.h_max)
        )

        self.model.addConstrs(
            self.c_i_j_h[i, j, h] <= self.d_i_j_h[i, j, h]
            for i in range(self.nb_courses)
            for j in range(self.nb_students)
            for h in range(self.h_max)
        )

        self.model.addConstrs(
            self.c_i_j_h[i, j, h] >= self.d_i_j_h[i, j, h] - 1 + self.w_i[i]
            for i in range(self.nb_courses)
            for j in range(self.nb_students)
            for h in range(self.h_max)
        )

        self.model.addConstrs(
            self.alpha <= self.x_j[j] for j in range(self.nb_students)
        )

        self.model.addConstrs(
            self.alpha <= self.y_j[j] for j in range(self.nb_students)
        )

        self.model.addConstr(self.lambda_ >= 0.5)
        self.model.addConstr(self.lambda_ <= 1)

        self.model.addConstrs(self.w_i[i] <= 1 for i in range(self.nb_courses))
        self.model.addConstrs(self.w_i[i] >= 0 for i in range(self.nb_courses))

        self.model.addConstrs(
            self.c_i_j_h[i, j, h] <= 1
            for i in range(self.nb_courses)
            for j in range(self.nb_courses)
            for h in range(self.h_max)
        )
        self.model.addConstrs(
            self.c_i_j_h[i, j, h] >= 0
            for i in range(self.nb_courses)
            for j in range(self.nb_students)
            for h in range(self.h_max)
        )

        #################################
        # Accepted students constraints #
        #################################

        for j in range(nb_accepted):
            self.model.addConstr(
                gp.quicksum(self.c_i_j_h[i, j, h] for i in range(self.nb_courses))
                == self.lambda_ + self.y_j[j],
                name="constraint on accepted students",
            )
            self.model.addConstrs(
                (
                    self.large * (self.d_i_j[i, j] - 1)
                    <= accepted_j_i[j, i] - self.b_i[i]
                )
                for i in range(self.nb_courses)
            )
            self.model.addConstrs(
                (
                    self.large * self.d_i_j[i, j] + self.small
                    >= accepted_j_i[j, i] - self.b_i[i]
                )
                for i in range(self.nb_courses)
            )

        ################################
        # Refused students constraints #
        ################################

        for j in range(nb_accepted, nb_accepted + nb_refused):
            j_shifted = j - nb_accepted
            self.model.addConstr(
                gp.quicksum(self.c_i_j[i, j] for i in range(self.nb_courses))
                + self.x_j[j]
                + self.small
                == self.lambda_,
                name="constraint on accepted students",
            )
            self.model.addConstrs(
                (
                    self.large * (self.d_i_j[i, j] - 1)
                    <= refused_j_i[j_shifted, i] - self.b_i[i]
                )
                for i in range(self.nb_courses)
            )
            self.model.addConstrs(
                (
                    self.large * self.d_i_j[i, j] + self.small
                    >= refused_j_i[j_shifted, i] - self.b_i[i]
                )
                for i in range(self.nb_courses)
            )

        # Goal function
        self.model.setObjective(self.alpha, gp.GRB.MAXIMIZE)
        self.model.params.outputflag = 0
        self.model.optimize()

        if self.model.status == gp.GRB.INFEASIBLE:
            raise ValueError("Model was proven to be infeasible.")
        elif self.model.status == gp.GRB.INF_OR_UNBD:
            raise ValueError("Model was proven to be either infeasible or unbounded.")
        elif self.model.status == gp.GRB.UNBOUNDED:
            raise ValueError("Model was proven to be unbounded.")
        elif self.model.status == gp.GRB.OPTIMAL:

            return {
                "lam": self.lambda_.X,
                "border": self.b_i.X,
                "poids": self.w_i.X,
            }

        else:
            logging.warning("Model status code: %s", self.model.status)
            raise ValueError("Model didn't find optimal solution.")
