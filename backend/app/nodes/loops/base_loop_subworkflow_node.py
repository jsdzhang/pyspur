from typing import Any, Dict, List
from pydantic import BaseModel, create_model

from ..base import BaseNodeInput, BaseNodeOutput
from ...execution.workflow_executor import WorkflowExecutor
from ..subworkflow.base_subworkflow_node import (
    BaseSubworkflowNode,
    BaseSubworkflowNodeConfig,
)
from ...schemas.workflow_schemas import WorkflowDefinitionSchema


class BaseLoopSubworkflowNodeConfig(BaseSubworkflowNodeConfig):
    loop_subworkflow: WorkflowDefinitionSchema


class BaseLoopSubworkflowNodeInput(BaseNodeInput):
    pass


class BaseLoopSubworkflowNodeOutput(BaseNodeOutput):
    pass


class BaseLoopSubworkflowNode(BaseSubworkflowNode):
    name = "loop_subworkflow_node"
    config_model = BaseLoopSubworkflowNodeConfig
    iteration: int
    loop_outputs: Dict[str, List[Dict[str, Any]]]

    def setup(self) -> None:
        super().setup()
        self.loop_outputs = {}
        self.iteration = 0

    def _update_loop_outputs(self, iteration_output: Dict[str, Dict[str, Any]]) -> None:
        """Update the loop_outputs dictionary with the current iteration's output"""
        for node_id, node_outputs in iteration_output.items():
            # Skip storing the special loop_history field
            if "loop_history" in node_outputs:
                node_outputs = {
                    k: v for k, v in node_outputs.items() if k != "loop_history"
                }

            if node_id not in self.loop_outputs:
                self.loop_outputs[node_id] = [node_outputs]
            else:
                self.loop_outputs[node_id].append(node_outputs)

    async def stopping_condition(self, input: Dict[str, Any]) -> bool:
        """Default stopping condition - override in subclasses"""
        return self.iteration >= 3

    async def run_iteration(self, input: Dict[str, Any]) -> Dict[str, Any]:
        """Run a single iteration of the loop subworkflow"""
        self.subworkflow = self.config.loop_subworkflow
        assert self.subworkflow is not None

        # Inject loop outputs into the input
        iteration_input = {**input, "loop_history": self.loop_outputs}

        # Execute the subworkflow
        workflow_executor = WorkflowExecutor(
            workflow=self.subworkflow, context=self.context
        )
        outputs = await workflow_executor.run(iteration_input)

        # Convert outputs to dict format
        iteration_outputs = {
            node_id: output.model_dump() for node_id, output in outputs.items()
        }

        # Update loop outputs with this iteration's results
        self._update_loop_outputs(iteration_outputs)

        # Get the output node's results
        output_node = next(
            node for node in self.subworkflow.nodes if node.node_type == "OutputNode"
        )
        return iteration_outputs[output_node.id]

    async def run(self, input: BaseModel) -> BaseModel:
        """Execute the loop subworkflow until stopping condition is met"""
        # Create output model dynamically based on input fields
        self.output_model = create_model(
            f"{self.name}",
            __base__=BaseLoopSubworkflowNodeOutput,
            **{
                field_name: (field_info.annotation, ...)  # type: ignore
                for field_name, field_info in input.model_fields.items()
            },
        )

        # Initialize state
        self.setup()
        current_input = input.model_dump()

        # Run iterations until stopping condition is met
        while not await self.stopping_condition(current_input):
            iteration_output = await self.run_iteration(current_input)
            current_input.update(iteration_output)
            self.iteration += 1

        print(f"Loop outputs: {self.loop_outputs}")
        # Return final state as BaseModel
        return self.output_model.model_validate(current_input)  # type: ignore


if __name__ == "__main__":
    from ...schemas.workflow_schemas import (
        WorkflowNodeSchema,
        WorkflowLinkSchema,
    )
    import asyncio
    from pprint import pprint

    async def main():
        node = BaseLoopSubworkflowNode(
            name="test_loop",
            config=BaseLoopSubworkflowNodeConfig(
                loop_subworkflow=LoopSubworkflowDefinitionSchema(
                    nodes=[
                        WorkflowNodeSchema(
                            id="loop_input",
                            node_type="InputNode",
                            config={
                                "output_schema": {
                                    "count": "int",
                                    "loop_history": "dict",
                                },
                                "enforce_schema": False,
                            },
                        ),
                        WorkflowNodeSchema(
                            id="increment",
                            node_type="PythonFuncNode",
                            config={
                                "code": """
previous_outputs = input_model.loop_input.loop_history.get('increment', [])
running_total = sum(output['count'] for output in previous_outputs) if previous_outputs else 0  
running_total += input_model.loop_input.count + 1
return {
    'count': input_model.loop_input.count + 1,
    'running_total': running_total
}
""",
                                "output_schema": {
                                    "count": "int",
                                    "running_total": "int",
                                },
                            },
                        ),
                        WorkflowNodeSchema(
                            id="loop_output",
                            node_type="OutputNode",
                            config={
                                "output_map": {"count": "increment.count"},
                                "output_schema": {"count": "int"},
                            },
                        ),
                    ],
                    links=[
                        WorkflowLinkSchema(
                            source_id="loop_input",
                            target_id="increment",
                        ),
                        WorkflowLinkSchema(
                            source_id="increment",
                            target_id="loop_output",
                        ),
                    ],
                ),
            ),
        )

        class TestInput(BaseNodeInput):
            count: int = 0

        input_data = TestInput()
        output = await node(input_data)
        pprint(output)
        pprint(node.subworkflow_output)

    asyncio.run(main())
