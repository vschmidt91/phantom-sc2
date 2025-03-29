import click
import yaml


def CommandWithConfigFile(config_file_param_name):
    class CustomCommandClass(click.Command):
        def invoke(self, ctx):
            config_file = ctx.params[config_file_param_name]
            if config_file is not None:
                with open(config_file) as f:
                    config_data = yaml.safe_load(f)
                # for key, value in config_data.items():
                #     if isinstance(value, list):
                #         ctx.params[key] = tuple(list(ctx.params[key]) + value)
                #     else:
                #         ctx.params[key] = value
                ctx.params.update(config_data)
            return super(CustomCommandClass, self).invoke(ctx)

    return CustomCommandClass
