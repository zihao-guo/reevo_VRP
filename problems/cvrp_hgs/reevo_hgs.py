import logging
import os
import subprocess

from reevo import ReEvo
from utils.utils import file_to_string

from .code_extraction import extract_cpp_code


class CVRPHGSReEvo(ReEvo):
    def init_prompt(self) -> None:
        # //modify Use the specialised C++ prompt stack for CVRP HGS.
        self.problem = self.cfg.problem.problem_name
        self.problem_desc = self.cfg.problem.description
        self.problem_size = self.cfg.problem.problem_size
        self.func_name = self.cfg.problem.func_name
        self.obj_type = self.cfg.problem.obj_type
        self.problem_type = self.cfg.problem.problem_type

        logging.info("Problem: " + self.problem)
        logging.info("Problem description: " + self.problem_desc)
        logging.info("Function name: " + self.func_name)

        self.prompt_dir = f"{self.root_dir}/prompts"
        self.output_file = f"{self.root_dir}/problems/{self.problem}/gpt.py"

        prompt_path_suffix = "_black_box" if self.problem_type == "black_box" else ""
        problem_prompt_path = f"{self.prompt_dir}/{self.problem}{prompt_path_suffix}"
        problem_utils_path = f"{problem_prompt_path}/utils"

        self.seed_func = file_to_string(f"{problem_prompt_path}/seed_func.txt")
        self.func_signature = file_to_string(f"{problem_prompt_path}/func_signature.txt")
        self.func_desc = file_to_string(f"{problem_prompt_path}/func_desc.txt")

        if os.path.exists(f"{problem_prompt_path}/external_knowledge.txt"):
            self.external_knowledge = file_to_string(
                f"{problem_prompt_path}/external_knowledge.txt"
            )
            self.long_term_reflection_str = self.external_knowledge
        else:
            self.external_knowledge = ""

        self.system_generator_prompt = file_to_string(
            f"{problem_utils_path}/system_generator.txt"
        )
        self.system_reflector_prompt = file_to_string(
            f"{self.prompt_dir}/common/system_reflector.txt"
        )
        self.user_reflector_st_prompt = file_to_string(
            f"{problem_utils_path}/user_reflector_st.txt"
        )
        self.user_reflector_lt_prompt = file_to_string(
            f"{self.prompt_dir}/common/user_reflector_lt.txt"
        )
        self.crossover_prompt = file_to_string(f"{problem_utils_path}/crossover.txt")
        self.mutation_prompt = file_to_string(f"{problem_utils_path}/mutation.txt")
        self.user_generator_prompt = file_to_string(
            f"{problem_utils_path}/user_generator.txt"
        ).format(
            func_name=self.func_name,
            problem_desc=self.problem_desc,
            func_desc=self.func_desc,
        )
        self.seed_prompt = file_to_string(f"{problem_utils_path}/seed.txt").format(
            seed_func=self.seed_func,
            func_name=self.func_name,
        )

        self.print_crossover_prompt = True
        self.print_mutate_prompt = True
        self.print_short_term_reflection_prompt = True
        self.print_long_term_reflection_prompt = True

    def init_population(self) -> None:
        logging.info("Evaluating seed function...")
        code = extract_cpp_code(self.seed_func)
        logging.info("Seed function code: \n" + str(code))
        seed_ind = {
            "stdout_filepath": f"problem_iter{self.iteration}_stdout0.txt",
            "code_path": f"problem_iter{self.iteration}_code0.py",
            "candidate_path": os.path.abspath(
                f"problem_iter{self.iteration}_candidate0_selective_route_exchange.cpp"
            ),
            "code": code,
            "response_id": 0,
        }
        self.seed_ind = seed_ind
        self.population = self.evaluate_population([seed_ind])

        if not self.seed_ind["exec_success"]:
            raise RuntimeError(
                f"Seed function is invalid. Please check the stdout file in {os.getcwd()}."
            )

        self.update_iter()

        system = self.system_generator_prompt
        user = (
            self.user_generator_prompt
            + "\n"
            + self.seed_prompt
            + "\n"
            + self.long_term_reflection_str
        )
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        logging.info(
            "Initial Population Prompt: \nSystem Prompt: \n"
            + system
            + "\nUser Prompt: \n"
            + user
        )

        responses = self.generator_llm.multi_chat_completion(
            [messages],
            self.cfg.init_pop_size,
            temperature=self.generator_llm.temperature + 0.3,
        )
        population = [
            self.response_to_individual(response, response_id)
            for response_id, response in enumerate(responses)
        ]
        self.population = self.evaluate_population(population)
        self.update_iter()

    def response_to_individual(
        self,
        response: str,
        response_id: int,
        file_name: str = None,
    ) -> dict:
        file_name = (
            f"problem_iter{self.iteration}_response{response_id}"
            if file_name is None
            else file_name
        )
        response_file = file_name + ".txt"
        with open(response_file, "w", encoding="utf-8") as file:
            file.writelines(response + "\n")

        code = extract_cpp_code(response)
        return {
            "stdout_filepath": file_name + "_stdout.txt",
            "code_path": f"problem_iter{self.iteration}_code{response_id}.py",
            "candidate_path": os.path.abspath(
                f"problem_iter{self.iteration}_candidate{response_id}_selective_route_exchange.cpp"
            ),
            "code": code,
            "response_id": response_id,
        }

    def _run_code(self, individual: dict, response_id) -> subprocess.Popen:
        # //modify Write candidate C++ to a unique file and pass that path to eval.py.
        logging.debug(f"Iteration {self.iteration}: Processing Code Run {response_id}")

        with open(individual["candidate_path"], "w", encoding="utf-8") as file:
            file.writelines(individual["code"] + "\n")

        with open(individual["stdout_filepath"], "w", encoding="utf-8") as stdout:
            eval_file_path = f"{self.root_dir}/problems/{self.problem}/eval.py"
            process = subprocess.Popen(
                [
                    "python",
                    "-u",
                    eval_file_path,
                    f"{self.problem_size}",
                    self.root_dir,
                    "train",
                    individual["candidate_path"],
                ],
                stdout=stdout,
                stderr=stdout,
            )

        from utils.utils import block_until_running

        block_until_running(
            individual["stdout_filepath"],
            log_status=True,
            iter_num=self.iteration,
            response_id=response_id,
        )
        return process

    def gen_short_term_reflection_prompt(self, ind1: dict, ind2: dict):
        if ind1["obj"] == ind2["obj"]:
            raise ValueError("Two individuals to crossover have the same objective value!")

        better_ind, worse_ind = (
            (ind1, ind2) if ind1["obj"] < ind2["obj"] else (ind2, ind1)
        )

        system = self.system_reflector_prompt
        user = self.user_reflector_st_prompt.format(
            func_name=self.func_name,
            func_desc=self.func_desc,
            problem_desc=self.problem_desc,
            worse_code=worse_ind["code"],
            better_code=better_ind["code"],
        )
        message = [{"role": "system", "content": system}, {"role": "user", "content": user}]

        if self.print_short_term_reflection_prompt:
            logging.info(
                "Short-term Reflection Prompt: \nSystem Prompt: \n"
                + system
                + "\nUser Prompt: \n"
                + user
            )
            self.print_short_term_reflection_prompt = False

        return message, worse_ind["code"], better_ind["code"]

    def crossover(self, short_term_reflection_tuple):
        reflection_content_lst, worse_code_lst, better_code_lst = short_term_reflection_tuple
        messages_lst = []
        for reflection, worse_code, better_code in zip(
            reflection_content_lst, worse_code_lst, better_code_lst
        ):
            system = self.system_generator_prompt
            user = self.crossover_prompt.format(
                user_generator=self.user_generator_prompt,
                worse_code=worse_code,
                better_code=better_code,
                reflection=reflection,
                func_name=self.func_name,
            )
            messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            messages_lst.append(messages)

            if self.print_crossover_prompt:
                logging.info(
                    "Crossover Prompt: \nSystem Prompt: \n"
                    + system
                    + "\nUser Prompt: \n"
                    + user
                )
                self.print_crossover_prompt = False

        response_lst = self.crossover_llm.multi_chat_completion(messages_lst)
        crossed_population = [
            self.response_to_individual(response, response_id)
            for response_id, response in enumerate(response_lst)
        ]
        assert len(crossed_population) == self.cfg.pop_size
        return crossed_population

    def mutate(self):
        system = self.system_generator_prompt
        user = self.mutation_prompt.format(
            user_generator=self.user_generator_prompt,
            reflection=self.long_term_reflection_str + self.external_knowledge,
            elitist_code=self.elitist["code"],
            func_name=self.func_name,
        )
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if self.print_mutate_prompt:
            logging.info(
                "Mutation Prompt: \nSystem Prompt: \n"
                + system
                + "\nUser Prompt: \n"
                + user
            )
            self.print_mutate_prompt = False

        responses = self.mutation_llm.multi_chat_completion(
            [messages],
            int(self.cfg.pop_size * self.mutation_rate),
        )
        return [
            self.response_to_individual(response, response_id)
            for response_id, response in enumerate(responses)
        ]
