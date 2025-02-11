# 🦾 Nidam: Self-Hosting LLMs Made Easy

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202-green.svg)](https://github.com/jileml/Nidam/blob/main/LICENSE)
[![Releases](https://img.shields.io/pypi/v/Nidam.svg?logo=pypi&label=PyPI&logoColor=gold)](https://pypi.org/project/Nidam)
[![CI](https://results.pre-commit.ci/badge/github/jileml/Nidam/main.svg)](https://results.pre-commit.ci/latest/github/jileml/Nidam/main)
[![X](https://badgen.net/badge/icon/@jilemlai/000000?icon=twitter&label=Follow)](https://twitter.com/jilemlai)
[![Community](https://badgen.net/badge/icon/Community/562f5d?icon=slack&label=Join)](https://l.jileml.com/join-slack)

Nidam allows developers to run **any open-source LLMs** (Llama 3.3, Qwen2.5, Phi3 and [more](#supported-models)) or **custom models** as **OpenAI-compatible APIs** with a single command. It features a [built-in chat UI](#chat-ui), state-of-the-art inference backends, and a simplified workflow for creating enterprise-grade cloud deployment with Docker, Kubernetes, and [jileCloud](#deploy-to-jilecloud).

Understand the [design philosophy of Nidam](https://www.jileml.com/blog/from-ollama-to-Nidam-running-llms-in-the-cloud).

## Get Started

Run the following commands to install Nidam and explore it interactively.

```bash
pip install nidam  # or pip3 install nidam
nidam hello
```

![hello](https://github.com/user-attachments/assets/5af19f23-1b34-4c45-b1e0-a6798b4586d1)

## Supported models

Nidam supports a wide range of state-of-the-art open-source LLMs. You can also add a [model repository to run custom models](#set-up-a-custom-repository) with Nidam.

| Model            | Parameters | Quantization | Required GPU  | Start a Server                      |
| ---------------- | ---------- | ------------ | ------------- | ----------------------------------- |
| Llama 3.3        | 70B        | -            | 80Gx2         | `nidam serve llama3.3:70b`        |
| Llama 3.2        | 3B         | -            | 12G           | `nidam serve llama3.2:3b`         |
| Llama 3.2 Vision | 11B        | -            | 80G           | `nidam serve llama3.2:11b-vision` |
| Mistral          | 7B         | -            | 24G           | `nidam serve mistral:7b`          |
| Qwen 2.5         | 1.5B       | -            | 12G           | `nidam serve qwen2.5:1.5b`        |
| Qwen 2.5 Coder   | 7B         | -            | 24G           | `nidam serve qwen2.5-coder:7b`    |
| Gemma 2          | 9B         | -            | 24G           | `nidam serve gemma2:9b`           |
| Phi3             | 3.8B       | -            | 12G           | `nidam serve phi3:3.8b`           |

...

For the full model list, see the [Nidam models repository](https://github.com/jileml/nidam-models).

## Start an LLM server

To start an LLM server locally, use the `nidam serve` command and specify the model version.

> [!NOTE]
> Nidam does not store model weights. A Hugging Face token (HF_TOKEN) is required for gated models.
> 1. Create your Hugging Face token [here](https://huggingface.co/settings/tokens).
> 2. Request access to the gated model, such as [meta-llama/Meta-Llama-3-8B](https://huggingface.co/meta-llama/Meta-Llama-3-8B).
> 3. Set your token as an environment variable by running:
>    ```bash
>    export HF_TOKEN=<your token>
>    ```

```bash
nidam serve llama3:8b
```

The server will be accessible at [http://localhost:3000](http://localhost:3000/), providing OpenAI-compatible APIs for interaction. You can call the endpoints with different frameworks and tools that support OpenAI-compatible APIs. Typically, you may need to specify the following:

- **The API host address**: By default, the LLM is hosted at [http://localhost:3000](http://localhost:3000/).
- **The model name:** The name can be different depending on the tool you use.
- **The API key**: The API key used for client authentication. This is optional.

Here are some examples:

<details>

<summary>OpenAI Python client</summary>

```python
from openai import OpenAI

client = OpenAI(base_url='http://localhost:3000/v1', api_key='na')

# Use the following func to get the available models
# model_list = client.models.list()
# print(model_list)

chat_completion = client.chat.completions.create(
    model="meta-llama/Meta-Llama-3-8B-Instruct",
    messages=[
        {
            "role": "user",
            "content": "Explain superconductors like I'm five years old"
        }
    ],
    stream=True,
)
for chunk in chat_completion:
    print(chunk.choices[0].delta.content or "", end="")
```

</details>


<details>

<summary>LlamaIndex</summary>

```python
from llama_index.llms.openai import OpenAI

llm = OpenAI(api_bese="http://localhost:3000/v1", model="meta-llama/Meta-Llama-3-8B-Instruct", api_key="dummy")
...
```
</details>

## Chat UI

Nidam provides a chat UI at the `/chat` endpoint for the launched LLM server at http://localhost:3000/chat.

<img width="800" alt="nidam_ui" src="https://github.com/jileml/Nidam/assets/5886138/8b426b2b-67da-4545-8b09-2dc96ff8a707">

## Chat with a model in the CLI

To start a chat conversation in the CLI, use the `nidam run` command and specify the model version.

```bash
nidam run llama3:8b
```

## Model repository

A model repository in Nidam represents a catalog of available LLMs that you can run. Nidam provides a default model repository that includes the latest open-source LLMs like Llama 3, Mistral, and Qwen2, hosted at [this GitHub repository](https://github.com/jileml/Nidam-models). To see all available models from the default and any added repository, use:

```bash
nidam model list
```

To ensure your local list of models is synchronized with the latest updates from all connected repositories, run:

```bash
nidam repo update
```

To review a model’s information, run:

```bash
nidam model get llama3:8b
```

### Add a model to the default model repository

You can contribute to the default model repository by adding new models that others can use. This involves creating and submitting a jile of the LLM. For more information, check out this [example pull request](https://github.com/jileml/Nidam-models/pull/1).

### Set up a custom repository

You can add your own repository to Nidam with custom models. To do so, follow the format in the default Nidam model repository with a `jiles` directory to store custom LLMs. You need to [build your jiles with jileML](https://docs.jileml.com/en/latest/guides/build-options.html) and submit them to your model repository.

First, prepare your custom models in a `jiles` directory following the guidelines provided by [jileML to build jiles](https://docs.jileml.com/en/latest/guides/build-options.html). Check out the [default model repository](https://github.com/jileml/Nidam-repo) for an example and read the [Developer Guide](https://github.com/jileml/Nidam/blob/main/DEVELOPMENT.md) for details.

Then, register your custom model repository with Nidam:

```bash
nidam repo add <repo-name> <repo-url>
```

**Note**: Currently, Nidam only supports adding public repositories.

## Deploy to jileCloud

Nidam supports LLM cloud deployment via jileML, the unified model serving framework, and jileCloud, an AI inference platform for enterprise AI teams. jileCloud provides fully-managed infrastructure optimized for LLM inference with autoscaling, model orchestration, observability, and many more, allowing you to run any AI model in the cloud.

[Sign up for jileCloud](https://www.jileml.com/) for free and [log in](https://docs.jileml.com/en/latest/jilecloud/how-tos/manage-access-token.html). Then, run `nidam deploy` to deploy a model to jileCloud:

```bash
nidam deploy llama3:8b
```

> [!NOTE]
> If you are deploying a gated model, make sure to set HF_TOKEN in enviroment variables.

Once the deployment is complete, you can run model inference on the jileCloud console:

<img width="800" alt="jilecloud_ui" src="https://github.com/jileml/Nidam/assets/65327072/4f7819d9-73ea-488a-a66c-f724e5d063e6">

## Community

Nidam is actively maintained by the jileML team. Feel free to reach out and join us in our pursuit to make LLMs more accessible and easy to use 👉 [Join our Slack community!](https://l.jileml.com/join-slack)

## Contributing

As an open-source project, we welcome contributions of all kinds, such as new features, bug fixes, and documentation. Here are some of the ways to contribute:

- Repost a bug by [creating a GitHub issue](https://github.com/jileml/Nidam/issues/new/choose).
- [Submit a pull request](https://github.com/jileml/Nidam/compare) or help review other developers’ [pull requests](https://github.com/jileml/Nidam/pulls).
- Add an LLM to the Nidam default model repository so that other users can run your model. See the [pull request template](https://github.com/jileml/Nidam-models/pull/1).
- Check out the [Developer Guide](https://github.com/jileml/Nidam/blob/main/DEVELOPMENT.md) to learn more.

## Acknowledgements

This project uses the following open-source projects:

- [jileml/jileml](https://github.com/jileml/jileml) for production level model serving
- [vllm-project/vllm](https://github.com/vllm-project/vllm) for production level LLM backend
- [blrchen/chatgpt-lite](https://github.com/blrchen/chatgpt-lite) for a fancy Web Chat UI
- [chujiezheng/chat_templates](https://github.com/chujiezheng/chat_templates)
- [astral-sh/uv](https://github.com/astral-sh/uv) for blazing fast model requirements installing

We are grateful to the developers and contributors of these projects for their hard work and dedication.
