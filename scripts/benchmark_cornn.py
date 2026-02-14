from collections import defaultdict

import cma
import matplotlib.pyplot as plt
import numpy as np
import streamlit as st

from phantom.learn.xcma import XCMA
from phantom.learn.xnes import XNES

import lib.CORNN as CORNN


class CMAAdapter:
    def __init__(self, x0, sigma0):
        opts = cma.CMAOptions()
        self.es = cma.CMAEvolutionStrategy(x0, sigma0, opts)

    def ask(self):
        x = self.es.ask()
        return np.asarray(x).T

    def tell(self, x, fx):
        self.es.tell(x.T.tolist(), fx)
        return self.es.stop()

    def recommend(self):
        return self.es.mean

class XNESAdapter:
    def __init__(self, x0, sigma0):
        self.es = XNES(x0, sigma0)

    def ask(self):
        z, x = self.es.ask()
        self.z = z
        return x

    def tell(self, x, fx):
        return self.es.tell(self.z, np.argsort(fx))

    def recommend(self):
        return self.es.loc

class XCMAAdapter:
    def __init__(self, x0, sigma0):
        self.es = XCMA(x0, sigma0)

    def ask(self):
        z, x = self.es.ask()
        self.z = z
        return x

    def tell(self, x, fx):
        print(min(fx))
        return self.es.tell(self.z, np.argsort(fx))

    def recommend(self):
        return self.es.loc

def single(d, fn, es):
    while True:
        x = es.ask()
        fx = list(map(fn, x.T))
        yield fn(es.recommend())
        # print(min(fx))
        if es.tell(x, fx):
            break

def single_fn(d, fn, es_list):
    streams = [single(d, fn, es) for es in es_list]
    return zip(*streams)

def benchmark(fn_dict, es_cls_dict):
    for name, (d, fn) in fn_dict.items():
        print(name, d, fn)
        x0 = np.zeros(d)
        sigma0 = 1.
        es_dict = {k: c(x0, sigma0) for k, c in es_cls_dict.items()}
        for results_tuple in single_fn(d, fn, es_dict.values()):
            results_dict = dict(zip(es_cls_dict.keys(), results_tuple))
            yield results_dict


if __name__ == "__main__":

    es_dict = {
        # "XCMA": XCMAAdapter,
        "CMA": CMAAdapter,
        "XNES": XNESAdapter,
    }

    fn_dict = {}
    function_dictionary = CORNN.get_benchmark_functions()
    model_dictionary = CORNN.get_NN_models()
    for fn, x_range, y_range, name in function_dictionary.values():
        training_data, test_data = CORNN.get_scaled_function_data(function_dictionary["Ackley"])
        for nn_name, nn in CORNN.get_NN_models().items():
            training_data, test_data = CORNN.get_scaled_function_data(function_dictionary["Ackley"])
            model_name = "Net_1_tanh_layer"
            model = model_dictionary[model_name]()
            b = CORNN.NN_Benchmark(training_data, test_data, model)
            d = b.get_weight_count()
            fn_dict[name] = d, b.training_set_evaluation

    st.title("🏆 Live Optimizer Race")
    col1, col2 = st.columns([3, 1])
    placeholder = st.empty()

    history = defaultdict(list)

    for step, results in enumerate(benchmark(fn_dict, es_dict)):
        if step > 100:
            break
        for k, v in results.items():
            history[k].append(v)
        with placeholder.container():
            fig, ax = plt.subplots(figsize=(10, 5))
            for name, losses in history.items():
                ax.plot(losses, label=name, lw=2)

            ax.set_yscale('log')
            ax.set_title(f"Optimization Progress (Step {step})")
            ax.set_xlabel("Iterations")
            ax.set_ylabel("Log Loss (Best Found)")
            ax.legend()
            ax.grid(True, which="both", ls="-", alpha=0.5)

            st.pyplot(fig)
            plt.close(fig)