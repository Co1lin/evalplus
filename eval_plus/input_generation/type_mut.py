from multipledispatch import dispatch

import copy
import random
import string
from typing import List, Any, Tuple, Set, Dict

from eval_plus.evaluation.evaluate import execute
from eval_plus.input_generation.mut_gen import MutateGen

MAX_MULTI_STEP_SIZE = 5


# decorator to use ingredients
class use_ingredient:
    def __init__(self, prob: float):
        assert 0 <= prob <= 0.95
        self.prob = prob

    def __call__(obj, func):
        def wrapper(self, seed_input):
            if random.random() < obj.prob and self.ingredients[type(seed_input)]:
                return random.choice(list(self.ingredients[type(seed_input)]))
            else:
                return func(self, seed_input)

        return wrapper


class TypedMutGen(MutateGen):
    def __init__(self, inputs: List, signature: str, contract_code: str):
        super().__init__(inputs, signature, contract_code)
        self.ingredients = {
            int: set(),
            float: set(),
            str: set(),
        }
        for x in inputs:
            self.fetch_ingredient(x)

    def seed_selection(self):
        # random for now.
        return random.choice(self.seed_pool)

    def mutate(self, seed_input: Any) -> List:
        new_input = copy.deepcopy(seed_input)

        while new_input == seed_input:
            new_input = self.typed_mutate(new_input)

        return new_input

    ########################
    # Type-aware mutation  #
    ########################

    # Simple primitives
    @dispatch(int)
    @use_ingredient(0.5)
    def typed_mutate(self, seed_input: int):
        @use_ingredient(0.5)
        def _impl(_, seed_input: int):
            return seed_input + random.randint(-1, 1)

        return _impl(self, seed_input)

    @dispatch(float)
    def typed_mutate(self, seed_input: float):
        @use_ingredient(0.5)
        def _impl(_, seed_input: float):
            if random.randint(0, 1):
                return seed_input + random.uniform(-1, 1)
            else:
                return seed_input * (1 + random.uniform(-0.5, 0.5))

        return _impl(self, seed_input)

    @dispatch(bool)
    def typed_mutate(self, seed_input: bool):
        return random.choice([True, False])

    # List-like
    def _mutate_list_like(self, seed_input):
        if len(seed_input) == 0:
            return []

        choice = random.randint(0, 3)
        idx = random.randint(0, len(seed_input) - 1)
        if choice == 0:  # remove one element
            seed_input.pop(random.randint(0, len(seed_input) - 1))
        elif choice == 1 and len(seed_input) > 0:  # add one mutated element
            seed_input.append(self.typed_mutate(seed_input[idx]))
        elif choice == 2 and len(seed_input) > 0:  # repeat one element
            seed_input.append(seed_input[idx])
        else:  # inplace element change
            seed_input[idx] = self.typed_mutate(seed_input[idx])
        return seed_input

    @dispatch(list)
    def typed_mutate(self, seed_input: List):
        return self._mutate_list_like(seed_input)

    @dispatch(tuple)
    def typed_mutate(self, seed_input: Tuple):
        return tuple(self._mutate_list_like(list(seed_input)))

    # String
    @use_ingredient(0.2)
    def typed_mutate_str_impl(self, seed_input: str):
        choice = random.randint(0, 2) if seed_input else 0
        if choice == 0 and self.ingredients[str]:  # insert an ingredient
            idx = random.randint(0, len(seed_input))
            return (
                seed_input[:idx]
                + random.choice(list(self.ingredients[str]))
                + seed_input[idx:]
            )
        # other choices assume len(seed_input) > 0
        elif choice == 1:  # replace a substring with empty or mutated string
            start = random.randint(0, len(seed_input) - 1)
            end = random.randint(start + 1, len(seed_input))
            mid = (
                "" if random.randint(0, 1) else self.typed_mutate(seed_input[start:end])
            )
            return seed_input[:start] + mid + seed_input[end:]
        elif choice == 2:  # repeat one element
            idx = random.randint(0, len(seed_input) - 1)
            return (
                seed_input[:idx]
                + seed_input[random.randint(0, len(seed_input) - 1)]
                + seed_input[idx:]
            )

        # random char
        return seed_input + random.choice(string.ascii_letters)

    @dispatch(str)
    def typed_mutate(self, seed_input: str):
        return self.typed_mutate_str_impl(seed_input)

    # Set
    @dispatch(set)
    def typed_mutate(self, seed_input: Set):
        return set(self._mutate_list_like(list(seed_input)))

    # Dict
    @dispatch(dict)
    def typed_mutate(self, seed_input: Dict):
        choice = random.randint(0, 2)
        if choice == 0 and len(seed_input) > 0:  # remove a kv
            del seed_input[random.choice(list(seed_input.keys()))]
        elif choice == 1:  # add a kv
            k = self.typed_mutate(random.choice(list(seed_input.keys())))
            v = self.typed_mutate(random.choice(list(seed_input.values())))
            seed_input[k] = v
        else:  # inplace value change
            k0, v0 = random.choice(list(seed_input.items()))
            seed_input[k0] = self.typed_mutate(v0)
        return seed_input

    ############################################
    # Fetching ingredients to self.ingredients #
    ############################################
    def fetch_ingredient(self, seed_input):
        self.typed_fetch(seed_input)

    @dispatch(int)
    def typed_fetch(self, seed_input: int):
        self.ingredients[int].add(seed_input)

    @dispatch(float)
    def typed_fetch(self, seed_input: float):
        self.ingredients[float].add(seed_input)

    @dispatch(str)
    def typed_fetch(self, seed_input: str):
        self.ingredients[str].add(seed_input)

    # List-like
    def _fetch_list_like(self, seed_input):
        for x in seed_input:
            if self.typed_fetch.dispatch(type(x)):
                self.fetch_ingredient(x)

    @dispatch(list)
    def typed_fetch(self, seed_input: List):
        self._fetch_list_like(seed_input)

    @dispatch(tuple)
    def typed_fetch(self, seed_input: Tuple):
        self._fetch_list_like(seed_input)

    @dispatch(set)
    def typed_fetch(self, seed_input: Set):
        self._fetch_list_like(seed_input)

    # Dict
    @dispatch(dict)
    def typed_fetch(self, seed_input: Dict):
        self._fetch_list_like(seed_input.keys())
        self._fetch_list_like(seed_input.values())

    def generate(self, num: int):
        while len(self.new_inputs) < num:
            new_input = self.seed_selection()
            # Multi-step instead of single-step
            for _ in range(random.randint(1, MAX_MULTI_STEP_SIZE)):
                new_input = self.mutate(new_input)
            if hash(str(new_input)) not in self.seed_hash:
                o = execute(self.contract_code, new_input, self.signature)
                if o != "timed out" and o != "thrown exception":
                    self.typed_fetch(new_input)
                    self.seed_pool.append(new_input)
                    self.seed_hash.add(hash(str(new_input)))
                    self.new_inputs.append(new_input)
        return self.new_inputs[:num]