// Copyright (c) 2020, NVIDIA CORPORATION. All rights reserved.
//
// Redistribution and use in source and binary forms, with or without
// modification, are permitted provided that the following conditions
// are met:
//  * Redistributions of source code must retain the above copyright
//    notice, this list of conditions and the following disclaimer.
//  * Redistributions in binary form must reproduce the above copyright
//    notice, this list of conditions and the following disclaimer in the
//    documentation and/or other materials provided with the distribution.
//  * Neither the name of NVIDIA CORPORATION nor the names of its
//    contributors may be used to endorse or promote products derived
//    from this software without specific prior written permission.
//
// THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS ``AS IS'' AND ANY
// EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
// IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
// PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR
// CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
// EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
// PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
// PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY
// OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
// (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
// OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#pragma once

/// \file

#include "src/clients/c++/experimental_api_v2/library/common.h"
#include "src/core/constants.h"
#include "src/core/grpc_service_v2.grpc.pb.h"
#include "src/core/model_config.pb.h"

namespace nvidia { namespace inferenceserver { namespace client {

/// The key-value map type to be included in the request
/// metadata
typedef std::map<std::string, std::string> Headers;

//==============================================================================
/// An InferenceServerGrpcClient object is used to perform any kind of
/// communication with the InferenceServer using gRPC protocol.
///
/// \code
///   std::unique_ptr<InferenceServerGrpcClient> client;
///   InferenceServerGrpcClient::Create(&client, "localhost:8001");
///   bool live;
///   client->IsServerLive(&live);
///   ...
///   ...
/// \endcode
///
class InferenceServerGrpcClient : public InferenceServerClient {
 public:
  /// Create a client that can be used to communicate with the server.
  /// \param client Returns a new InferenceServerGrpcClient object.
  /// \param server_url The inference server name and port.
  /// \param verbose If true generate verbose output when contacting
  /// the inference server.
  /// \return Error object indicating success or failure.
  static Error Create(
      std::unique_ptr<InferenceServerGrpcClient>* client,
      const std::string& server_url, bool verbose = false);

  /// Contact the inference server and get its liveness.
  /// \param live Returns whether the server is live or not.
  /// \param headers Optional map specifying additional HTTP headers to include
  /// in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the request.
  Error IsServerLive(bool* live, const Headers& headers = Headers());

  /// Contact the inference server and get its readiness.
  /// \param ready Returns whether the server is ready or not.
  /// \param headers Optional map specifying additional HTTP headers to include
  /// in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the request.
  Error IsServerReady(bool* ready, const Headers& headers = Headers());

  /// Contact the inference server and get the readiness of specified model.
  /// \param ready Returns whether the specified model is ready or not.
  /// \param model_name The name of the model to check for readiness.
  /// \param model_version The version of the model to check for readiness.
  /// The default value is an empty string which means then the server will
  /// choose a version based on the model and internal policy.
  /// \param headers Optional map specifying additional HTTP headers to include
  /// in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the request.
  Error IsModelReady(
      bool* ready, const std::string& model_name,
      const std::string& model_version = "",
      const Headers& headers = Headers());

  /// Contact the inference server and get its metadata.
  /// \param server_metadata Returns the server metadata as
  /// SeverMetadataResponse message.
  /// \param headers Optional map specifying additional HTTP headers to include
  /// in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the request.
  Error GetServerMetadata(
      ServerMetadataResponse* server_metadata,
      const Headers& headers = Headers());

  /// Contact the inference server and get the metadata of specified model.
  /// \param model_metadata Returns model metadata as ModelMetadataResponse
  /// message.
  /// \param model_name The name of the model to get metadata.
  /// \param model_version The version of the model to get metadata.
  /// The default value is an empty string which means then the server will
  /// choose a version based on the model and internal policy.
  /// \param headers Optional map specifying additional HTTP headers to include
  /// in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the request.
  Error GetModelMetadata(
      ModelMetadataResponse* model_metadata, const std::string& model_name,
      const std::string& model_version = "",
      const Headers& headers = Headers());

  /// Contact the inference server and get the configuration of specified model.
  /// \param model_config Returns model config as ModelConfigResponse
  /// message.
  /// \param model_name The name of the model to get configuration.
  /// \param model_version The version of the model to get configuration.
  /// The default value is an empty string which means then the server will
  /// choose a version based on the model and internal policy.
  /// \param headers Optional map specifying additional HTTP headers to include
  /// in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the request.
  Error GetModelConfig(
      ModelConfigResponse* model_config, const std::string& model_name,
      const std::string& model_version = "",
      const Headers& headers = Headers());

  /// Run synchronous inference on server.
  /// \param result Returns the result of inference.
  /// \param options The options for inference request.
  /// \param inputs The vector of InferInput describing the model inputs.
  /// \param outputs Optional vector of InferRequestedOutput describing how the
  /// output must be returned. If not provided then all the outputs in the model
  /// config will be returned as default settings.
  /// \param headers Optional map specifying additional HTTP headers to include
  /// in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the
  /// request.
  Error Infer(
      InferResult** result, const InferOptions& options,
      const std::vector<InferInput*>& inputs,
      const std::vector<const InferRequestedOutput*>& outputs =
          std::vector<const InferRequestedOutput*>(),
      const Headers& headers = Headers());

 private:
  InferenceServerGrpcClient(const std::string& url, bool verbose);

  // Initializes the request message for inference request.
  Error InitModelInferRequest(
      const InferOptions& options, const std::vector<InferInput*>& inputs,
      const std::vector<const InferRequestedOutput*>& outputs);

  // GRPC end point.
  std::unique_ptr<GRPCInferenceService::Stub> stub_;

  // Enable verbose output
  const bool verbose_;

  // request for GRPC call, one request object can be used for multiple calls
  // since it can be overwritten as soon as the GRPC send finishes.
  ModelInferRequest infer_request_;
};

//==============================================================================
/// An InferResultGrpc instance is used  to access and interpret the
/// response of an inference request from GRPC endpoint. This object
/// holds data for all requested outputs.
///
class InferResultGrpc : public InferResult {
 public:
  /// Create a InferResult instance to interpret server response.
  /// \param infer_result Returns a new InferResult object.
  /// \param response  The response of server for an inference request.
  /// \return Error object indicating success or failure.
  static Error Create(
      InferResult** infer_result, std::shared_ptr<ModelInferResponse> response);

  /// See InferResult::ModelName(std::string* name)
  Error ModelName(std::string* name) const override;

  /// See InferResult::ModelVersion(std::string* version)
  Error ModelVersion(std::string* version) const override;

  /// See InferResult::Id(std::string* id)
  Error Id(std::string* id) const override;

  /// See InferResult::Shape(const std::string& output_name,
  ///  std::vector<int64_t>* shape)
  Error Shape(const std::string& output_name, std::vector<int64_t>* shape)
      const override;

  /// See InferResult::Datatype(
  ///    const std::string& output_name, std::string* datatype)
  Error Datatype(
      const std::string& output_name, std::string* datatype) const override;

  /// See InferResult::RawData(
  ///    const std::string& output_name, const uint8_t** buf,
  ///    size_t* byte_size)
  Error RawData(
      const std::string& output_name, const uint8_t** buf,
      size_t* byte_size) const override;

  /// See InferResult::DebugString()
  std::string DebugString() const override { return response_->DebugString(); }

 private:
  InferResultGrpc(std::shared_ptr<ModelInferResponse> response);

  std::map<std::string, const ModelInferResponse::InferOutputTensor*>
      output_name_to_result_map_;

  std::shared_ptr<ModelInferResponse> response_;
};


//==============================================================================
// An GrpcInferRequest represents an inflght inference request on gRPC.
//
class GrpcInferRequest : public InferRequest {
 public:
  GrpcInferRequest()
      : grpc_status_(), grpc_response_(std::make_shared<ModelInferResponse>())
  {
  }

  friend InferenceServerGrpcClient;

 private:
  // Variables for GRPC call
  grpc::ClientContext grpc_context_;
  grpc::Status grpc_status_;
  std::shared_ptr<ModelInferResponse> grpc_response_;
};


}}}  // namespace nvidia::inferenceserver::client
