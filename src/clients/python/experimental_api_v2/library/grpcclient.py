# Copyright (c) 2020, NVIDIA CORPORATION. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#  * Neither the name of NVIDIA CORPORATION nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS ``AS IS'' AND ANY
# EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY
# OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import base64
import numpy as np
import grpc
import rapidjson as json
import threading
import queue
from google.protobuf.json_format import MessageToJson

from tritongrpcclient import grpc_service_v2_pb2
from tritongrpcclient import grpc_service_v2_pb2_grpc
from tritongrpcclient.utils import *


def get_error_grpc(rpc_error):
    return InferenceServerException(
        msg=rpc_error.details(),
        status=str(rpc_error.code()),
        debug_details=rpc_error.debug_error_string())


def raise_error_grpc(rpc_error):
    raise get_error_grpc(rpc_error) from None


def _get_inference_request(model_name, inputs, model_version, request_id,
                           outputs, sequence_id, sequence_start, sequence_end,
                           priority, timeout):
    request = grpc_service_v2_pb2.ModelInferRequest()
    request.model_name = model_name
    request.model_version = model_version
    if request_id != "":
        request.id = request_id
    for infer_input in inputs:
        request.inputs.extend([infer_input._get_tensor()])
    if outputs is not None:
        for infer_output in outputs:
            request.outputs.extend([infer_output._get_tensor()])
    if sequence_id != 0:
        request.parameters['sequence_id'].int64_param = sequence_id
        request.parameters['sequence_start'].bool_param = sequence_start
        request.parameters['sequence_end'].bool_param = sequence_end
    if priority != 0:
        request.parameters['priority'].int64_param = priority
    if timeout is not None:
        request.parameters['timeout'].int64_param = timeout
    return request


class InferenceServerClient:
    """An InferenceServerClient object is used to perform any kind of
    communication with the InferenceServer using gRPC protocol.

    Parameters
    ----------
    url : str
        The inference server URL, e.g. 'localhost:8001'.     

    verbose : bool
        If True generate verbose output. Default value is False.
    
    Raises
    ------
    Exception
        If unable to create a client.

    """

    def __init__(self, url, verbose=False):
        # FixMe: Are any of the channel options worth exposing?
        # https://grpc.io/grpc/core/group__grpc__arg__keys.html
        self._channel = grpc.insecure_channel(url, options=None)
        self._client_stub = grpc_service_v2_pb2_grpc.GRPCInferenceServiceStub(
            self._channel)
        self._verbose = verbose

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()

    def __del__(self):
        self.close()

    def close(self):
        """Close the client. Any future calls to server
        will result in an Error.

        """
        self._channel.close()

    def is_server_live(self, headers=None):
        """Contact the inference server and get liveness.

        Parameters
        ----------
        headers: dict
            Optional dictionary specifying additional HTTP
            headers to include in the request.

        Returns
        -------
        bool
            True if server is live, False if server is not live.

        Raises
        ------
        InferenceServerException
            If unable to get liveness.

        """
        if headers is not None:
            metadata = headers.items()
        else:
            metadata = ()
        try:
            request = grpc_service_v2_pb2.ServerLiveRequest()
            response = self._client_stub.ServerLive(request=request,
                                                    metadata=metadata)
            return response.live
        except grpc.RpcError as rpc_error:
            raise_error_grpc(rpc_error)

    def is_server_ready(self, headers=None):
        """Contact the inference server and get readiness.

        Parameters
        ----------
        headers: dict
            Optional dictionary specifying additional HTTP
            headers to include in the request.

        Returns
        -------
        bool
            True if server is ready, False if server is not ready.

        Raises
        ------
        InferenceServerException
            If unable to get readiness.

        """
        if headers is not None:
            metadata = headers.items()
        else:
            metadata = ()
        try:
            request = grpc_service_v2_pb2.ServerReadyRequest()
            response = self._client_stub.ServerReady(request=request,
                                                     metadata=metadata)
            return response.ready
        except grpc.RpcError as rpc_error:
            raise_error_grpc(rpc_error)

    def is_model_ready(self, model_name, model_version="", headers=None):
        """Contact the inference server and get the readiness of specified model.

        Parameters
        ----------
        model_name: str
            The name of the model to check for readiness.
        model_version: str
            The version of the model to check for readiness. The default value
            is an empty string which means then the server will choose a version
            based on the model and internal policy.
        headers: dict
            Optional dictionary specifying additional HTTP
            headers to include in the request.

        Returns
        -------
        bool
            True if the model is ready, False if not ready.

        Raises
        ------
        InferenceServerException
            If unable to get model readiness.

        """
        if headers is not None:
            metadata = headers.items()
        else:
            metadata = ()
        try:
            request = grpc_service_v2_pb2.ModelReadyRequest(
                name=model_name, version=model_version)
            response = self._client_stub.ModelReady(request=request,
                                                    metadata=metadata)
            return response.ready
        except grpc.RpcError as rpc_error:
            raise_error_grpc(rpc_error)

    def get_server_metadata(self, headers=None, as_json=False):
        """Contact the inference server and get its metadata.

        Parameters
        ----------
        headers: dict
            Optional dictionary specifying additional HTTP
            headers to include in the request.
        as_json : bool
            If True then returns server metadata as a json dict,
            otherwise as a protobuf message. Default value is False.

        Returns
        -------
        dict or protobuf message
            The JSON dict or ServerMetadataResponse message
            holding the metadata.

        Raises
        ------
        InferenceServerException
            If unable to get server metadata.

        """
        if headers is not None:
            metadata = headers.items()
        else:
            metadata = ()
        try:
            request = grpc_service_v2_pb2.ServerMetadataRequest()
            response = self._client_stub.ServerMetadata(request=request,
                                                        metadata=metadata)
            if as_json:
                return json.loads(MessageToJson(response))
            else:
                return response
        except grpc.RpcError as rpc_error:
            raise_error_grpc(rpc_error)

    def get_model_metadata(self,
                           model_name,
                           model_version="",
                           headers=None,
                           as_json=False):
        """Contact the inference server and get the metadata for specified model.

        Parameters
        ----------
        model_name: str
            The name of the model
        model_version: str
            The version of the model to get metadata. The default value
            is an empty string which means then the server will choose
            a version based on the model and internal policy.
        headers: dict
            Optional dictionary specifying additional HTTP
            headers to include in the request.
        as_json : bool
            If True then returns model metadata as a json dict, otherwise
            as a protobuf message. Default value is False.

        Returns
        -------
        dict or protobuf message 
            The JSON dict or ModelMetadataResponse message holding
            the metadata.

        Raises
        ------
        InferenceServerException
            If unable to get model metadata.

        """
        if headers is not None:
            metadata = headers.items()
        else:
            metadata = ()
        try:
            request = grpc_service_v2_pb2.ModelMetadataRequest(
                name=model_name, version=model_version)
            response = self._client_stub.ModelMetadata(request=request,
                                                       metadata=metadata)
            if as_json:
                return json.loads(MessageToJson(response))
            else:
                return response
        except grpc.RpcError as rpc_error:
            raise_error_grpc(rpc_error)

    def get_model_config(self,
                         model_name,
                         model_version="",
                         headers=None,
                         as_json=False):
        """Contact the inference server and get the configuration for specified model.

        Parameters
        ----------
        model_name: str
            The name of the model
        model_version: str
            The version of the model to get configuration. The default value
            is an empty string which means then the server will choose
            a version based on the model and internal policy.
        headers: dict
            Optional dictionary specifying additional HTTP
            headers to include in the request.
        as_json : bool
            If True then returns configuration as a json dict, otherwise
            as a protobuf message. Default value is False.

        Returns
        -------
        dict or protobuf message 
            The JSON dict or ModelConfigResponse message holding
            the metadata.

        Raises
        ------
        InferenceServerException
            If unable to get model configuration.

        """
        if headers is not None:
            metadata = headers.items()
        else:
            metadata = ()
        try:
            request = grpc_service_v2_pb2.ModelConfigRequest(
                name=model_name, version=model_version)
            response = self._client_stub.ModelConfig(request=request,
                                                     metadata=metadata)
            if as_json:
                return json.loads(MessageToJson(response))
            else:
                return response
        except grpc.RpcError as rpc_error:
            raise_error_grpc(rpc_error)

    def get_model_repository_index(self, headers=None, as_json=False):
        """Get the index of model repository contents

        Parameters
        ----------
        headers: dict
            Optional dictionary specifying additional HTTP
            headers to include in the request.
        as_json : bool
            If True then returns model repository index
            as a json dict, otherwise as a protobuf message.
            Default value is False.

        Returns
        -------
        dict or protobuf message 
            The JSON dict or RepositoryIndexResponse message holding
            the model repository index.

        """
        if headers is not None:
            metadata = headers.items()
        else:
            metadata = ()
        try:
            request = grpc_service_v2_pb2.RepositoryIndexRequest()
            response = self._client_stub.RepositoryIndex(request=request,
                                                         metadata=metadata)
            if as_json:
                return json.loads(MessageToJson(response))
            else:
                return response
        except grpc.RpcError as rpc_error:
            raise_error_grpc(rpc_error)

    def load_model(self, model_name, headers=None):
        """Request the inference server to load or reload specified model.

        Parameters
        ----------
        model_name : str
            The name of the model to be loaded.
        headers: dict
            Optional dictionary specifying additional HTTP
            headers to include in the request.

        Raises
        ------
        InferenceServerException
            If unable to load the model.

        """
        if headers is not None:
            metadata = headers.items()
        else:
            metadata = ()
        try:
            request = grpc_service_v2_pb2.RepositoryModelLoadRequest(
                model_name=model_name)
            self._client_stub.RepositoryModelLoad(request=request,
                                                  metadata=metadata)
        except grpc.RpcError as rpc_error:
            raise_error_grpc(rpc_error)

    def unload_model(self, model_name, headers=None):
        """Request the inference server to unload specified model.

        Parameters
        ----------
        model_name : str
            The name of the model to be unloaded.
        headers: dict
            Optional dictionary specifying additional HTTP
            headers to include in the request.

        Raises
        ------
        InferenceServerException
            If unable to unload the model.

        """
        if headers is not None:
            metadata = headers.items()
        else:
            metadata = ()
        try:
            request = grpc_service_v2_pb2.RepositoryModelUnloadRequest(
                model_name=model_name)
            self._client_stub.RepositoryModelUnload(request=request,
                                                    metadata=metadata)
        except grpc.RpcError as rpc_error:
            raise_error_grpc(rpc_error)

    def get_inference_statistics(self,
                                 model_name,
                                 model_version="",
                                 headers=None,
                                 as_json=False):
        """Get the inference statistics for the specified model name and
        version.

        Parameters
        ----------
        model_name : str
            The name of the model to be unloaded.
        model_version: str
            The version of the model to get inference statistics. The
            default value is an empty string which means then the server
            will return the statistics of all available model versions.
        headers: dict
            Optional dictionary specifying additional HTTP
            headers to include in the request.
        as_json : bool
            If True then returns inference statistics
            as a json dict, otherwise as a protobuf message.
            Default value is False.

        Raises
        ------
        InferenceServerException
            If unable to get the model inference statistics.

        """
        if headers is not None:
            metadata = headers.items()
        else:
            metadata = ()
        try:
            request = grpc_service_v2_pb2.ModelStatisticsRequest(
                name=model_name, version=model_version)
            response = self._client_stub.ModelStatistics(request=request,
                                                         metadata=metadata)
            if as_json:
                return json.loads(MessageToJson(response))
            else:
                return response
        except grpc.RpcError as rpc_error:
            raise_error_grpc(rpc_error)

    def get_system_shared_memory_status(self,
                                        region_name="",
                                        headers=None,
                                        as_json=False):
        """Request system shared memory status from the server.

        Parameters
        ----------
        region_name : str
            The name of the region to query status. The default
            value is an empty string, which means that the status
            of all active system shared memory will be returned.
        headers: dict
            Optional dictionary specifying additional HTTP
            headers to include in the request.
        as_json : bool
            If True then returns system shared memory status as a 
            json dict, otherwise as a protobuf message. Default
            value is False.

        Returns
        -------
        dict or protobuf message 
            The JSON dict or SystemSharedMemoryStatusResponse message holding
            the system shared memory status.

        Raises
        ------
        InferenceServerException
            If unable to get the status of specified shared memory.

        """
        if headers is not None:
            metadata = headers.items()
        else:
            metadata = ()
        try:
            request = grpc_service_v2_pb2.SystemSharedMemoryStatusRequest(
                name=region_name)
            response = self._client_stub.SystemSharedMemoryStatus(
                request=request, metadata=metadata)
            if as_json:
                return json.loads(MessageToJson(response))
            else:
                return response
        except grpc.RpcError as rpc_error:
            raise_error_grpc(rpc_error)

    def register_system_shared_memory(self,
                                      name,
                                      key,
                                      byte_size,
                                      offset=0,
                                      headers=None):
        """Request the server to register a system shared memory with the
        following specification.

        Parameters
        ----------
        name : str
            The name of the region to register.
        key : str 
            The key of the underlying memory object that contains the
            system shared memory region.
        byte_size : int
            The size of the system shared memory region, in bytes.
        offset : int
            Offset, in bytes, within the underlying memory object to
            the start of the system shared memory region. The default
            value is zero.
        headers: dict
            Optional dictionary specifying additional HTTP
            headers to include in the request.

        Raises
        ------
        InferenceServerException
            If unable to register the specified system shared memory.     

        """
        if headers is not None:
            metadata = headers.items()
        else:
            metadata = ()
        try:
            request = grpc_service_v2_pb2.SystemSharedMemoryRegisterRequest(
                name=name, key=key, offset=offset, byte_size=byte_size)
            self._client_stub.SystemSharedMemoryRegister(request=request,
                                                         metadata=metadata)
        except grpc.RpcError as rpc_error:
            raise_error_grpc(rpc_error)

    def unregister_system_shared_memory(self, name="", headers=None):
        """Request the server to unregister a system shared memory with the
        specified name.

        Parameters
        ----------
        name : str
            The name of the region to unregister. The default value is empty
            string which means all the system shared memory regions will be
            unregistered.
        headers: dict
            Optional dictionary specifying additional HTTP
            headers to include in the request.
        
        Raises
        ------
        InferenceServerException
            If unable to unregister the specified system shared memory region.

        """
        if headers is not None:
            metadata = headers.items()
        else:
            metadata = ()
        try:
            request = grpc_service_v2_pb2.SystemSharedMemoryUnregisterRequest(
                name=name)
            self._client_stub.SystemSharedMemoryUnregister(request=request,
                                                           metadata=metadata)
        except grpc.RpcError as rpc_error:
            raise_error_grpc(rpc_error)

    def get_cuda_shared_memory_status(self,
                                      region_name="",
                                      headers=None,
                                      as_json=False):
        """Request cuda shared memory status from the server.

        Parameters
        ----------
        region_name : str
            The name of the region to query status. The default
            value is an empty string, which means that the status
            of all active cuda shared memory will be returned.
        headers: dict
            Optional dictionary specifying additional HTTP
            headers to include in the request.
        as_json : bool
            If True then returns cuda shared memory status as a 
            json dict, otherwise as a protobuf message. Default
            value is False.

        Returns
        -------
        dict or protobuf message 
            The JSON dict or CudaSharedMemoryStatusResponse message holding
            the cuda shared memory status.

        Raises
        ------
        InferenceServerException
            If unable to get the status of specified shared memory.

        """

        if headers is not None:
            metadata = headers.items()
        else:
            metadata = ()
        try:
            request = grpc_service_v2_pb2.CudaSharedMemoryStatusRequest(
                name=region_name)
            response = self._client_stub.CudaSharedMemoryStatus(
                request=request, metadata=metadata)
            if as_json:
                return json.loads(MessageToJson(response))
            else:
                return response
        except grpc.RpcError as rpc_error:
            raise_error_grpc(rpc_error)

    def register_cuda_shared_memory(self,
                                    name,
                                    raw_handle,
                                    device_id,
                                    byte_size,
                                    headers=None):
        """Request the server to register a system shared memory with the
        following specification.

        Parameters
        ----------
        name : str
            The name of the region to register.
        raw_handle : bytes 
            The raw serialized cudaIPC handle in base64 encoding.
        device_id : int
            The GPU device ID on which the cudaIPC handle was created.
        byte_size : int
            The size of the cuda shared memory region, in bytes.
        headers: dict
            Optional dictionary specifying additional HTTP
            headers to include in the request.

        Raises
        ------
        InferenceServerException
            If unable to register the specified cuda shared memory.     

        """
        if headers is not None:
            metadata = headers.items()
        else:
            metadata = ()
        try:
            request = grpc_service_v2_pb2.CudaSharedMemoryRegisterRequest(
                name=name,
                raw_handle=base64.b64decode(raw_handle),
                device_id=device_id,
                byte_size=byte_size)
            self._client_stub.CudaSharedMemoryRegister(request=request,
                                                       metadata=metadata)
        except grpc.RpcError as rpc_error:
            raise_error_grpc(rpc_error)

    def unregister_cuda_shared_memory(self, name="", headers=None):
        """Request the server to unregister a cuda shared memory with the
        specified name.

        Parameters
        ----------
        name : str
            The name of the region to unregister. The default value is empty
            string which means all the cuda shared memory regions will be
            unregistered.
        headers: dict
            Optional dictionary specifying additional HTTP
            headers to include in the request.
        
        Raises
        ------
        InferenceServerException
            If unable to unregister the specified cuda shared memory region.

        """
        if headers is not None:
            metadata = headers.items()
        else:
            metadata = ()
        try:
            request = grpc_service_v2_pb2.CudaSharedMemoryUnregisterRequest(
                name=name)
            self._client_stub.CudaSharedMemoryUnregister(request=request,
                                                         metadata=metadata)
        except grpc.RpcError as rpc_error:
            raise_error_grpc(rpc_error)

    def infer(self,
              model_name,
              inputs,
              model_version="",
              outputs=None,
              request_id="",
              sequence_id=0,
              sequence_start=False,
              sequence_end=False,
              priority=0,
              timeout=None,
              headers=None):
        """Run synchronous inference using the supplied 'inputs' requesting
        the outputs specified by 'outputs'.

        Parameters
        ----------
        model_name: str
            The name of the model to run inference.
        inputs : list
            A list of InferInput objects, each describing data for a input
            tensor required by the model.
        model_version : str
            The version of the model to run inference. The default value
            is an empty string which means then the server will choose
            a version based on the model and internal policy.
        outputs : list
            A list of InferRequestedOutput objects, each describing how the output
            data must be returned. If not specified all outputs produced
            by the model will be returned using default settings.
        request_id : str
            Optional identifier for the request. If specified will be returned
            in the response. Default value is an empty string which means no
            request_id will be used.
        sequence_id : int
            The unique identifier for the sequence being represented by the
            object. Default value is 0 which means that the request does not
            belong to a sequence.
        sequence_start : bool
            Indicates whether the request being added marks the start of the 
            sequence. Default value is False. This argument is ignored if
            'sequence_id' is 0.
        sequence_end : bool
            Indicates whether the request being added marks the end of the 
            sequence. Default value is False. This argument is ignored if
            'sequence_id' is 0.
        priority : int
            Indicates the priority of the request. Priority value zero
            indicates that the default priority level should be used
            (i.e. same behavior as not specifying the priority parameter).
            Lower value priorities indicate higher priority levels. Thus
            the highest priority level is indicated by setting the parameter
            to 1, the next highest is 2, etc. If not provided, the server
            will handle the request using default setting for the model.
        timeout : int
            The timeout value for the request, in microseconds. If the request
            cannot be completed within the time the server can take a
            model-specific action such as terminating the request. If not
            provided, the server will handle the request using default setting
            for the model.
        headers : dict
            Optional dictionary specifying additional HTTP headers to include
            in the request.

        Returns
        -------
        InferResult
            The object holding the result of the inference, including the
            statistics.

        Raises
        ------
        InferenceServerException
            If server fails to perform inference.
        """

        if headers is not None:
            metadata = headers.items()
        else:
            metadata = ()

        request = _get_inference_request(model_name=model_name,
                                         inputs=inputs,
                                         model_version=model_version,
                                         request_id=request_id,
                                         outputs=outputs,
                                         sequence_id=sequence_id,
                                         sequence_start=sequence_start,
                                         sequence_end=sequence_end,
                                         priority=priority,
                                         timeout=timeout)

        try:
            response = self._client_stub.ModelInfer(request=request,
                                                    metadata=metadata)
            result = InferResult(response)
            return result
        except grpc.RpcError as rpc_error:
            raise_error_grpc(rpc_error)

    def async_infer(self,
                    model_name,
                    inputs,
                    callback,
                    model_version="",
                    outputs=None,
                    request_id="",
                    sequence_id=0,
                    sequence_start=False,
                    sequence_end=False,
                    priority=0,
                    timeout=None,
                    headers=None):
        """Run asynchronous inference using the supplied 'inputs' requesting
        the outputs specified by 'outputs'.

        Parameters
        ----------
        model_name: str
            The name of the model to run inference.
        inputs : list
            A list of InferInput objects, each describing data for a input
            tensor required by the model.
        callback : function
            Python function that is invoked once the request is completed.
            The function must reserve the last two arguments (result, error)
            to hold InferResult and InferenceServerException objects
            respectively which will be provided to the function when executing
            the callback. The ownership of these objects will be given to the
            user. The 'error' would be None for a successful inference.
        model_version: str
            The version of the model to run inference. The default value
            is an empty string which means then the server will choose
            a version based on the model and internal policy.
        outputs : list
            A list of InferRequestedOutput objects, each describing how the output
            data must be returned. If not specified all outputs produced
            by the model will be returned using default settings.
        request_id : str
            Optional identifier for the request. If specified will be returned
            in the response. Default value is an empty string which means no
            request_id will be used.
        sequence_id : int
            The unique identifier for the sequence being represented by the
            object. Default value is 0 which means that the request does not
            belong to a sequence.
        sequence_start: bool
            Indicates whether the request being added marks the start of the 
            sequence. Default value is False. This argument is ignored if
            'sequence_id' is 0.
        sequence_end: bool
            Indicates whether the request being added marks the end of the 
            sequence. Default value is False. This argument is ignored if
            'sequence_id' is 0.
        priority : int
            Indicates the priority of the request. Priority value zero
            indicates that the default priority level should be used
            (i.e. same behavior as not specifying the priority parameter).
            Lower value priorities indicate higher priority levels. Thus
            the highest priority level is indicated by setting the parameter
            to 1, the next highest is 2, etc. If not provided, the server
            will handle the request using default setting for the model.
        timeout : int
            The timeout value for the request, in microseconds. If the request
            cannot be completed within the time the server can take a
            model-specific action such as terminating the request. If not
            provided, the server will handle the request using default setting
            for the model.
        headers: dict
            Optional dictionary specifying additional HTTP
            headers to include in the request.
    
        Raises
        ------
        InferenceServerException
            If server fails to issue inference.
        """

        def wrapped_callback(call_future):
            error = result = None
            try:
                result = InferResult(call_future.result())
            except grpc.RpcError as rpc_error:
                error = get_error_grpc(rpc_error)
            callback(result=result, error=error)

        if headers is not None:
            metadata = headers.items()
        else:
            metadata = ()

        request = _get_inference_request(model_name=model_name,
                                         inputs=inputs,
                                         model_version=model_version,
                                         request_id=request_id,
                                         outputs=outputs,
                                         sequence_id=sequence_id,
                                         sequence_start=sequence_start,
                                         sequence_end=sequence_end,
                                         priority=priority,
                                         timeout=timeout)

        try:
            self._call_future = self._client_stub.ModelInfer.future(
                request=request, metadata=metadata)
            self._call_future.add_done_callback(wrapped_callback)
        except grpc.RpcError as rpc_error:
            raise_error_grpc(rpc_error)

    def async_stream_infer(self,
                           model_name,
                           inputs,
                           stream,
                           model_version="",
                           outputs=None,
                           request_id="",
                           sequence_id=0,
                           sequence_start=False,
                           sequence_end=False,
                           priority=0,
                           timeout=None):
        """Runs an asynchronous inference over gRPC bi-directional streaming
        API.

        Parameters
        ----------
        model_name: str
            The name of the model to run inference.
        inputs : list
            A list of InferInput objects, each describing data for a input
            tensor required by the model.
        stream : InferStream
            The stream to use for sending/receiving inference requests/response.
        model_version: str
            The version of the model to run inference. The default value
            is an empty string which means then the server will choose
            a version based on the model and internal policy.
        outputs : list
            A list of InferRequestedOutput objects, each describing how the output
            data must be returned. If not specified all outputs produced
            by the model will be returned using default settings.
        request_id : str
            Optional identifier for the request. If specified will be returned
            in the response. Default value is an empty string which means no
            request_id will be used.
        sequence_id : int
            The unique identifier for the sequence being represented by the
            object. Default value is 0 which means that the request does not
            belong to a sequence.
        sequence_start: bool
            Indicates whether the request being added marks the start of the 
            sequence. Default value is False. This argument is ignored if
            'sequence_id' is 0.
        sequence_end: bool
            Indicates whether the request being added marks the end of the 
            sequence. Default value is False. This argument is ignored if
            'sequence_id' is 0.
        priority : int
            Indicates the priority of the request. Priority value zero
            indicates that the default priority level should be used
            (i.e. same behavior as not specifying the priority parameter).
            Lower value priorities indicate higher priority levels. Thus
            the highest priority level is indicated by setting the parameter
            to 1, the next highest is 2, etc. If not provided, the server
            will handle the request using default setting for the model.
        timeout : int
            The timeout value for the request, in microseconds. If the request
            cannot be completed within the time the server can take a
            model-specific action such as terminating the request. If not
            provided, the server will handle the request using default setting
            for the model.
    
        Raises
        ------
        InferenceServerException
            If server fails to issue inference.
        """

        if not stream._is_initialized():
            # Inititate the response stream handler if required.
            if stream._headers is not None:
                metadata = stream._headers.items()
            else:
                metadata = ()

            try:
                stream._init_handler(
                    self._client_stub.ModelStreamInfer(_RequestIterator(stream),
                                                       metadata=metadata))
            except grpc.RpcError as rpc_error:
                raise_error_grpc(rpc_error)

        request = _get_inference_request(model_name=model_name,
                                         inputs=inputs,
                                         model_version=model_version,
                                         request_id=request_id,
                                         outputs=outputs,
                                         sequence_id=sequence_id,
                                         sequence_start=sequence_start,
                                         sequence_end=sequence_end,
                                         priority=priority,
                                         timeout=timeout)
        # Enqueues the request to the stream
        stream._enqueue_request(request)


class InferInput:
    """An object of InferInput class is used to describe
    input tensor for an inference request.

    Parameters
    ----------
    name : str
        The name of input whose data will be described by this object
    shape : list
        The shape of the associated input.
    datatype : str
        The datatype of the associated input.

    """

    def __init__(self, name, shape, datatype):
        self._input = grpc_service_v2_pb2.ModelInferRequest().InferInputTensor()
        self._input.name = name
        self._input.ClearField('shape')
        self._input.shape.extend(shape)
        self._input.datatype = datatype

    def name(self):
        """Get the name of input associated with this object.

        Returns
        -------
        str
            The name of input
        """
        return self._input.name

    def datatype(self):
        """Get the datatype of input associated with this object.

        Returns
        -------
        str
            The datatype of input
        """
        return self._input.datatype

    def shape(self):
        """Get the shape of input associated with this object.

        Returns
        -------
        list
            The shape of input
        """
        return self._input.shape

    def set_shape(self, shape):
        """Set the shape of input.

        Parameters
        ----------
        shape : list
            The shape of the associated input.
        """
        self._input.ClearField('shape')
        self._input.shape.extend(shape)

    def set_data_from_numpy(self, input_tensor):
        """Set the tensor data from the specified numpy array for
        input associated with this object.

        Parameters
        ----------
        input_tensor : numpy array
            The tensor data in numpy array format
        
        Raises
        ------
        InferenceServerException
            If failed to set data for the tensor.
        """
        if not isinstance(input_tensor, (np.ndarray,)):
            raise_error("input_tensor must be a numpy array")
        dtype = np_to_triton_dtype(input_tensor.dtype)
        if self._input.datatype != dtype:
            raise_error(
                "got unexpected datatype {} from numpy array, expected {}".
                format(dtype, self._input.datatype))
        valid_shape = True
        if len(self._input.shape) != len(input_tensor.shape):
            valid_shape = False
        for i in range(len(self._input.shape)):
            if self._input.shape[i] != input_tensor.shape[i]:
                valid_shape = False
        if not valid_shape:
            raise_error(
                "got unexpected numpy array shape [{}], expected [{}]".format(
                    str(input_tensor.shape)[1:-1],
                    str(self._input.shape)[1:-1]))
        if self._input.datatype == "BYTES":
            self._input.contents.raw_contents = serialize_byte_tensor(
                input_tensor).tobytes()
        else:
            self._input.contents.raw_contents = input_tensor.tobytes()

    def set_shared_memory(self, region_name, byte_size, offset=0):
        """Set the tensor data from the specified shared memory region.

        Parameters
        ----------
        region_name : str
            The name of the shared memory region holding tensor data.
        byte_size : int
            The size of the shared memory region holding tensor data.
        offset : int
            The offset, in bytes, into the region where the data for
            the tensor starts. The default value is 0.
        
        """

        self._input.parameters[
            'shared_memory_region'].string_param = region_name
        self._input.parameters[
            'shared_memory_byte_size'].int64_param = byte_size
        if offset != 0:
            self._input.parameters['shared_memory_offset'].int64_param = offset

    def _get_tensor(self):
        """Retrieve the underlying InferInputTensor message.
        Returns
        -------
        protobuf message 
            The underlying InferInputTensor protobuf message.
        """
        return self._input


class InferRequestedOutput:
    """An object of InferRequestedOutput class is used to describe a
    requested output tensor for an inference request.

    Parameters
    ----------
    name : str
        The name of output tensor to associate with this object
    class_count : int
        The number of classifications to be requested. The default
        value is 0 which means the classification results are not 
        requested.
    """

    def __init__(self, name, class_count=0):
        self._output = grpc_service_v2_pb2.ModelInferRequest(
        ).InferRequestedOutputTensor()
        self._output.name = name
        if class_count != 0:
            self._output.parameters['classification'].int64_param = class_count

    def name(self):
        """Get the name of output associated with this object.

        Returns
        -------
        str
            The name of output
        """
        return self._output.name

    def set_shared_memory(self, region_name, byte_size, offset=0):
        """Marks the output to return the inference result in
        specified shared memory region.

        Parameters
        ----------
        region_name : str
            The name of the shared memory region to hold tensor data.
        byte_size : int
            The size of the shared memory region to hold tensor data.
        offset : int
            The offset, in bytes, into the region where the data for
            the tensor starts. The default value is 0.
        
        """

        self._output.parameters[
            'shared_memory_region'].string_param = region_name
        self._output.parameters[
            'shared_memory_byte_size'].int64_param = byte_size
        if offset != 0:
            self._output.parameters['shared_memory_offset'].int64_param = offset

    def _get_tensor(self):
        """Retrieve the underlying InferRequestedOutputTensor message.
        Returns
        -------
        protobuf message 
            The underlying InferRequestedOutputTensor protobuf message.
        """
        return self._output


class InferResult:
    """An object of InferResult class holds the response of
    an inference request and provide methods to retrieve
    inference results.

    Parameters
    ----------
    result : protobuf message
        The ModelInferResponse returned by the server
    """

    def __init__(self, result):
        self._result = result

    def as_numpy(self, name):
        """Get the tensor data for output associated with this object
        in numpy format

        Parameters
        ----------
        name : str
            The name of the output tensor whose result is to be retrieved.
    
        Returns
        -------
        numpy array
            The numpy array containing the response data for the tensor or
            None if the data for specified tensor name is not found.
        """
        for output in self._result.outputs:
            if output.name == name:
                shape = []
                for value in output.shape:
                    shape.append(value)

                datatype = output.datatype
                if len(output.contents.raw_contents) != 0:
                    if datatype == 'BYTES':
                        # String results contain a 4-byte string length
                        # followed by the actual string characters. Hence,
                        # need to decode the raw bytes to convert into
                        # array elements.
                        np_array = deserialize_bytes_tensor(
                            output.contents.raw_contents)
                    else:
                        np_array = np.frombuffer(
                            output.contents.raw_contents,
                            dtype=triton_to_np_dtype(datatype))
                elif len(output.contents.byte_contents) != 0:
                    np_array = np.array(output.contents.byte_contents)
                np_array = np.resize(np_array, shape)
                return np_array
        return None

    def get_output(self, name, as_json=False):
        """Retrieves the InferOutputTensor corresponding to the
        named ouput.

        Parameters
        ----------
        name : str
            The name of the tensor for which Output is to be
            retrieved.
        as_json : bool
            If True then returns response as a json dict, otherwise
            as a protobuf message. Default value is False.
    
        Returns
        -------
        protobuf message or dict
            If a InferOutputTensor with specified name is present in
            ModelInferResponse then returns it as a protobuf messsage
            or dict, otherwise returns None. 
        """
        for output in self._result.outputs:
            if output.name == name:
                if as_json:
                    return json.loads(MessageToJson(output))
                else:
                    return output

        return None

    def get_response(self, as_json=False):
        """Retrieves the complete ModelInferResponse as a
        json dict object or protobuf message

        Parameters
        ----------
        as_json : bool
            If True then returns response as a json dict, otherwise
            as a protobuf message. Default value is False.
    
        Returns
        -------
        protobuf message or dict
            The underlying ModelInferResponse as a protobuf message or dict.
        """
        if as_json:
            return json.loads(MessageToJson(self._result))
        else:
            return self._result


class InferStream:
    """Supports sending inference requests and receiving corresponding
    requests on a gRPC bi-directional stream.

    Parameters
    ----------
    callback : function
        Python function that is invoked upon receiving response from
        the underlying stream. The function must reserve the last two
        arguments (result, error) to hold InferResult and
        InferenceServerException objects respectively which will be
        provided to the function when executing the callback. The
        ownership of these objects will be given to the user. The
        'error' would be None for a successful inference.
    headers: dict
            Optional dictionary specifying additional HTTP
            headers to include while establising gRPC stream.
    """

    def __init__(self, callback, headers=None):
        self._callback = callback
        self._request_queue = queue.Queue()
        self._headers = headers
        self._handler = None

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()

    def __del__(self):
        self.close()

    def close(self):
        """Gracefully close underlying gRPC streams. Note that this call
        blocks till response of all currently enqueued requests are not
        received.
        """
        if self._is_initialized():
            self._request_queue.put(None)
            if self._handler.is_alive():
                self._handler.join()
            self._handler = None

    def _is_initialized(self):
        """Returns whether the handler to this stream object
        is initialized.
        """
        return (self._handler is not None)

    def _init_handler(self, response_iterator):
        """Initializes the handler to process the response from
        stream and execute the callbacks.

        Parameters
        ----------
        response_iterator : iterator
            The iterator over the gRPC response stream.

        """
        if self._is_initialized():
            raise_error(
                'Attempted to initialize already initialized InferStream')
        # Create a new thread to handle the gRPC response stream
        self._handler = threading.Thread(target=self._process_response,
                                         args=(response_iterator,))
        self._handler.start()

    def _enqueue_request(self, request):
        """Enqueues the specified request object to be provided
        in gRPC request stream.

        Parameters
        ----------
        request : ModelInferRequest
            The protobuf message holding the ModelInferRequest

        """
        self._request_queue.put(request)

    def _get_request(self):
        """Returns the request details in the order they were added.
        The call to this function will block until the requests
        are available in the queue. InferStream._enqueue_request
        adds the request to the queue.

        Returns
        -------
        protobuf message
            The ModelInferRequest protobuf message.

        """
        request = self._request_queue.get()
        return request

    def _process_response(self, responses):
        """Worker thread function to iterate through the response stream and
        executes the provided callbacks. 

        Parameters
        ----------
        responses : iterator
            The iterator to the response from the server for the
            requests in the stream.
        
        """
        try:
            for response in responses:
                result = error = None
                if response.error_message != "":
                    error = InferenceServerException(msg=response.error_message)
                else:
                    result = InferResult(response.infer_response)
                self._callback(result=result, error=error)
        except grpc.RpcError as rpc_error:
            error = get_error_grpc(rpc_error)
            self._callback(result=None, error=error)


class _RequestIterator:
    """An iterator class to provide data tp gRPC request stream.

    Parameters
    ----------
    stream : InferStream
        The InferStream that holds the context to an active stream.

    """

    def __init__(self, stream):
        self._stream = stream

    def __iter__(self):
        return self

    def __next__(self):
        request = self._stream._get_request()
        if request is None:
            raise StopIteration

        return request
